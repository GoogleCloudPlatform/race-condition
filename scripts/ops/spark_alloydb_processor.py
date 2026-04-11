# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

####################################################################
###   ⚡ Spark Lightning Engine ⚡
####################################################################

import os
import argparse
from dotenv import load_dotenv

from pyspark.sql.functions import col, udf, explode
from pyspark.sql.types import StringType, ArrayType, StructType, StructField
from google.cloud import storage

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("--project_id", default="")
parser.add_argument("--location", default="")
parser.add_argument("--processor_id", default="")
parser.add_argument("--gcs_file_location", default="")
parser.add_argument("--alloydb_ip", default="")
parser.add_argument("--alloydb_user", default="")
parser.add_argument("--alloydb_pass", default="")
parser.add_argument("--alloydb_schema", default="local_dev")
parser.add_argument("--alloydb_instance_uri", default="")
parser.add_argument("--city", default="Las Vegas", help="The city to assign to these chunks")
args, unknown = parser.parse_known_args()

is_local = os.environ.get("LOCAL_DEV", "false").lower() == "true"

PROJECT_ID = args.project_id or os.environ.get("PROJECT_ID", "n26-devkey-simulation-dev")
LOCATION = args.location or os.environ.get("LOCATION", "us")
PROCESSOR_ID = args.processor_id or os.environ.get("PROCESSOR_ID", "776a2fcf1a6908bc")
GCS_FILE_LOCATION = args.gcs_file_location or os.environ.get("GCS_FILE_LOCATION", "gs://n26-xch/laws_and_regulations")
CITY_NAME = args.city

# AlloyDB Connection properties
alloydb_ip = args.alloydb_ip or os.environ.get("ALLOYDB_IP", "127.0.0.1") # Uses IP of AlloyDB proxy which is locally bound, or Dev DB
alloydb_port = os.environ.get("ALLOYDB_PORT", "5433" if is_local else "5432")
alloydb_user = args.alloydb_user or os.environ.get("ALLOYDB_USER", "postgres")
alloydb_pass = args.alloydb_pass or os.environ.get("ALLOYDB_PASSWORD") or os.environ.get("ALLOYDB_PASS")

# IMPORTANT: Default to `local_dev` natively if running locally, otherwise `public` to match the non-local environment
alloydb_schema = args.alloydb_schema or os.environ.get("ALLOYDB_SCHEMA") or ("local_dev" if is_local else "public")

ALLOYDB_INSTANCE_URI = args.alloydb_instance_uri or os.environ.get("ALLOYDB_INSTANCE_URI")

# We append ?options=-c search_path=XYZ for JDBC to hit the right schema natively if needed
jdbc_url = f"jdbc:postgresql://{alloydb_ip}:{alloydb_port}/postgres?sslmode=disable&options=-c%20search_path={alloydb_schema}"

####################################################################
###   Document AI Processor
####################################################################
# We configure max 15 pages per Document AI call because of synchronous limits.
MAX_PAGES_PER_CALL = 15

def process_document(gcs_uri: str):
    """Uses Document AI to parse the PDF, splitting it if it exceeds limits, and returns semantic chunks."""
    from google.cloud import documentai
    from google.api_core.client_options import ClientOptions
    import pypdf
    import io

    if not PROCESSOR_ID:
         with open("/tmp/spark_worker.log", "a") as f: f.write("Warning: PROCESSOR_ID is missing on worker.\n")
         return []

    opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    # Read the file from GCS
    bucket_name = gcs_uri.split("/")[2]
    blob_name = "/".join(gcs_uri.split("/")[3:])
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    content = blob.download_as_bytes()

    chunks = []

    try:
        pdf_reader = pypdf.PdfReader(io.BytesIO(content))
        total_pages = len(pdf_reader.pages)

        for i in range(0, total_pages, MAX_PAGES_PER_CALL):
            pdf_writer = pypdf.PdfWriter()
            chunk_pages = pdf_reader.pages[i:i + MAX_PAGES_PER_CALL]
            for page in chunk_pages:
                pdf_writer.add_page(page)

            out_stream = io.BytesIO()
            pdf_writer.write(out_stream)
            out_stream.seek(0)
            chunk_content = out_stream.read()

            with open("/tmp/spark_worker.log", "a") as f: f.write(f"Created chunk content of {len(chunk_content)} bytes for {gcs_uri}\n")

            raw_document = documentai.RawDocument(content=chunk_content, mime_type="application/pdf")
            request = documentai.ProcessRequest(name=name, raw_document=raw_document)

            try:
                result = client.process_document(request=request)
                document = result.document

                text = document.text
                if not text and hasattr(document, "document_layout"):
                    try:
                        blocks_text = []
                        for block in document.document_layout.blocks:
                            if block.text_block and block.text_block.text:
                                blocks_text.append(block.text_block.text)
                        text = "\n".join(blocks_text)
                    except Exception as e:
                        with open("/tmp/spark_worker.log", "a") as f: f.write(f"Layout extraction error: {e}\n")

                with open("/tmp/spark_worker.log", "a") as f: f.write(f"Extracted {len(text) if text else 0} chars, {len(document.pages) if hasattr(document, 'pages') and document.pages else 0} pages. Doc preview: {str(document)[:100]}\n")
                if not text:
                    continue
                # Fallback to simple text chunking: split into chunks of ~4000 characters
                chunk_size = 4000
                for k in range(0, len(text), chunk_size):
                    chunk_text = text[k:k+chunk_size].strip()
                    if chunk_text:
                        chunks.append((gcs_uri, chunk_text))
            except Exception as inner_e:
                with open("/tmp/spark_worker.log", "a") as f: f.write(f"Inner error: {inner_e}\n")
                raise inner_e

        with open("/tmp/spark_worker.log", "a") as f: f.write(f"Returning {len(chunks)} chunks for {gcs_uri}\n")
        return chunks
    except Exception as e:
        with open("/tmp/spark_worker.log", "a") as f: f.write(f"Outer error: {e}\n")
        chunks.append((gcs_uri, f"ERROR: {e}"))

    if not chunks:
        chunks.append((gcs_uri, "EMPTY_RESULT"))

    return chunks

def main():
    with open("/tmp/spark_main.log", "w") as f: f.write("main() started\n")

    if is_local:
        with open("/tmp/spark_main.log", "a") as f: f.write("LOCAL_DEV is true\n")
        print("Running in LOCAL_DEV mode. Initializing local SparkSession...")
        from pyspark.sql import SparkSession
        # Use simple local master
        spark = SparkSession.builder \
            .master("local[*]") \
            .appName("LegalDocsProcessor-Local") \
            .config("spark.jars.packages", "org.postgresql:postgresql:42.6.0") \
            .config("spark.jars", "gcs-connector-hadoop3-latest.jar") \
            .config("spark.hadoop.fs.gs.impl", "com.google.cloud.hadoop.fs.gcs.GoogleHadoopFileSystem") \
            .config("spark.hadoop.fs.AbstractFileSystem.gs.impl", "com.google.cloud.hadoop.fs.gcs.GoogleHadoopFS") \
            .config("spark.hadoop.google.cloud.auth.service.account.enable", "true") \
            .getOrCreate()
        spark.sparkContext.setLogLevel("ERROR")
    else:
        print("Running in Dataproc Serverless mode (Batch)...")
        from google.cloud.dataproc_spark_connect import DataprocSparkSession
        from google.cloud.dataproc_v1 import Session

        session = Session()
        spark = DataprocSparkSession.builder \
            .config("spark.dataproc.engine", "lightningEngine") \
            .appName("LegalDocsProcessor") \
            .dataprocSessionConfig(session) \
            .getOrCreate()

    # 1. List PDF files from GCS
    storage_client = storage.Client()
    bucket_name = GCS_FILE_LOCATION.split("/")[2]
    prefix = "/".join(GCS_FILE_LOCATION.split("/")[3:])
    blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
    pdf_uris = [f"gs://{bucket_name}/{blob.name}" for blob in blobs if blob.name.endswith(".pdf")]

    with open("/tmp/spark_main.log", "a") as f: f.write(f"pdf_uris: {pdf_uris}\n")

    if not pdf_uris:
        print("No PDFs found.")
        return

    # Create a DataFrame of URIs
    uri_df = spark.createDataFrame([(uri,) for uri in pdf_uris], ["gcs_uri"])

    with open("/tmp/spark_main.log", "a") as f: f.write("Created uri_df\n")

    # 2 & 3. Read them using Google Document AI and chunk them semantically
    chunk_schema = ArrayType(StructType([
        StructField("document_uri", StringType(), False),
        StructField("chunk_text", StringType(), False)
    ]))

    process_udf = udf(process_document, chunk_schema)
    chunked_df = uri_df.withColumn("chunks", process_udf(col("gcs_uri"))) \
                       .select(explode(col("chunks")).alias("chunk")) \
                       .select("chunk.*")

    # -------------------------------------------------------------
    # Adapt DataFrame to match the AlloyDB `rules` table schema
    # Expected columns: source_file (str), chunk_id (int), city (str), text (str)
    # The `embedding` column is intentionally excluded here as AlloyDB's
    # `ai.initialize_embeddings` function takes care of generation automatically.
    # -------------------------------------------------------------
    import pyspark.sql.functions as F

    # Get the basename of the URI for source_file
    final_df = chunked_df \
        .withColumn("source_file", F.element_at(F.split("document_uri", "/"), -1)) \
        .withColumn("chunk_id", F.abs(F.hash("chunk_text") % 1000000000)) \
        .withColumn("city", F.lit(CITY_NAME)) \
        .withColumn("text", F.col("chunk_text")) \
        .select("source_file", "chunk_id", "city", "text")

    with open("/tmp/spark_main.log", "a") as f: f.write("Created final_df\n")

    if is_local:
        with open("/tmp/spark_main.log", "a") as f: f.write("Connecting to local JDBC\n")
        print(f"Connecting to AlloyDB at {alloydb_ip} via JDBC (Local Mode using Auth Proxy)...")
        if not alloydb_ip:
            print("Error: ALLOYDB_IP is empty. Please set it in your .env file.")
            return

        print("Writing chunks to AlloyDB (via PySpark JDBC)...")
        # Target table incorporates explicit schema to ensure we write safely to local_dev.
        target_table = f"{alloydb_schema}.rules"

        try:
            import sys
            print("Calling final_df.count()...")
            sys.stdout.flush()
            count = final_df.count()
            print(f"Total chunks to write: {count}")
            sys.stdout.flush()
        except Exception as e:
            import sys
            print(f"Exception calling count: {e}")
            sys.stdout.flush()
            raise e

        if count > 0:
            final_df.write.format("jdbc") \
            .option("url", jdbc_url) \
            .option("dbtable", target_table) \
            .option("user", alloydb_user) \
            .option("password", alloydb_pass) \
            .option("driver", "org.postgresql.Driver") \
            .mode("append") \
            .save()
    else:
        print("Connecting to AlloyDB via Python Connector (Serverless Mode)...")
        alloydb_instance_uri = ALLOYDB_INSTANCE_URI
        if not alloydb_instance_uri:
             print("Error: ALLOYDB_INSTANCE_URI is missing from arguments or .env")
             return

        from google.cloud.alloydb.connector import Connector
        import sqlalchemy

        def getconn():
            with Connector() as connector:
                conn = connector.connect(
                    alloydb_instance_uri,
                    "pg8000",
                    user=alloydb_user,
                    password=alloydb_pass,
                    db="postgres",
                )
                return conn

        # In SQLAlchemy pg8000 URL, appending options doesn't work out of the box so
        # we configure schema routing manually or pass connect_args
        pool = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
            connect_args={"options": f"-c search_path={alloydb_schema}"}
        )

        print("Writing chunks to AlloyDB (via pandas)...")
        pdf = final_df.toPandas()
        with pool.connect() as db_conn:
             # Appending strictly to "rules" since our connection args set search_path
             pdf.to_sql("rules", db_conn, if_exists="append", index=False)

    print("Done processing and writing chunks.")

if __name__ == "__main__":
    main()
