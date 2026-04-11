// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package config

import (
	"fmt"
	"log"
	"os"
	"strconv"

	"github.com/joho/godotenv"
)

// Load attempts to load a .env file.
// It logs a warning if the file is missing but does not fail.
func Load() {
	if err := godotenv.Load(); err != nil {
		log.Println("⚠️  Warning: No .env file found. Using system environment variables.")
	}
}

// Require returns the value of an environment variable or panics if it's missing.
func Require(key string) string {
	val := os.Getenv(key)
	if val == "" {
		msg := fmt.Sprintf("❌ CRITICAL ERROR: Required configuration variable '%s' is missing.\n"+
			"Please ensure it is set in your .env file or environment.\n"+
			"Check .env.example for required variables.", key)
		panic(msg)
	}
	return val
}

// Optional returns the value of an environment variable or a default value if missing.
func Optional(key string, defaultValue string) string {
	val := os.Getenv(key)
	if val == "" {
		return defaultValue
	}
	return val
}

// ValidatePort ensures a string is a valid port number (1-65535).
func ValidatePort(val string) error {
	p, err := strconv.Atoi(val)
	if err != nil {
		return fmt.Errorf("invalid port number: %s", val)
	}
	if p < 1 || p > 65535 {
		return fmt.Errorf("port number out of range: %d", p)
	}
	return nil
}
