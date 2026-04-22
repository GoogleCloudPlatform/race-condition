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

# Pins the contract: db_initial_password defaults to a random_password,
# but a user-supplied value takes precedence.
#
# Google providers mocked: tests run offline; only the random + local logic
# is under test here. The random provider isn't mocked because run 1
# overrides random_password.result explicitly via override_resource;
# mocking would just add another layer without changing what's tested.
#
# command = plan is used throughout. random_password.db_initial.result is
# "(known after apply)", so the first run block uses override_resource +
# override_during = plan to stub a sentinel value -- letting us assert
# that local.db_password flows from random_password.db_initial.result
# without forcing an apply (which would otherwise fail on mock-stubbed
# google_sql_database_instance / IAM regex validation downstream).
#
# Note: assertions that compare local.db_password are wrapped in
# nonsensitive() because coalesce() propagates the sensitive flag from
# var.db_initial_password (sensitive=true) and random_password.result
# (sensitive by default). Without nonsensitive(), the equality check
# fails with "got (sensitive value)" in some TF / state-cache combinations.

mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "test-project"
  region     = "us-central1"
}

run "uses_random_password_when_var_is_null" {
  command = plan

  variables {
    db_initial_password = null # explicit: shield from ambient terraform.tfvars
  }

  override_resource {
    target          = random_password.db_initial
    override_during = plan
    values = {
      result = "RAND_FALLBACK_SENTINEL"
    }
  }

  assert {
    condition     = nonsensitive(local.db_password) == "RAND_FALLBACK_SENTINEL"
    error_message = "When var.db_initial_password is null, local.db_password must come from random_password.db_initial.result"
  }
}

run "honors_user_supplied_password" {
  command = plan

  variables {
    db_initial_password = "MyExplicitPassword123"
  }

  assert {
    condition     = nonsensitive(local.db_password) == "MyExplicitPassword123"
    error_message = "When var.db_initial_password is set, local.db_password must equal that value"
  }
}

run "random_password_length_is_32" {
  command = plan

  assert {
    condition     = random_password.db_initial.length == 32
    error_message = "Generated password length must be exactly 32 (security floor + entropy budget)"
  }
}

run "password_is_alphanumeric_for_shell_safety" {
  command = plan
  assert {
    condition     = random_password.db_initial.special == false
    error_message = "Password must be alphanumeric — downstream local-exec passes it via PGPASSWORD in bash double-quoted strings; specials would break shell interpolation"
  }
}
