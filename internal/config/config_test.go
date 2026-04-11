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
	"os"
	"testing"
)

func TestRequire(t *testing.T) {
	// Set a test variable
	os.Setenv("TEST_REQUIRED_VAR", "value")
	defer os.Unsetenv("TEST_REQUIRED_VAR")

	val := Require("TEST_REQUIRED_VAR")
	if val != "value" {
		t.Errorf("Expected 'value', got '%s'", val)
	}

	// Test panic on missing variable
	defer func() {
		if r := recover(); r == nil {
			t.Errorf("Require did not panic on missing variable")
		}
	}()
	Require("NON_EXISTENT_VAR")
}

func TestOptional(t *testing.T) {
	// Set a test variable
	os.Setenv("TEST_OPTIONAL_VAR", "value")
	defer os.Unsetenv("TEST_OPTIONAL_VAR")

	val := Optional("TEST_OPTIONAL_VAR", "default")
	if val != "value" {
		t.Errorf("Expected 'value', got '%s'", val)
	}

	// Test default value on missing variable
	valMissing := Optional("MISSING_OPTIONAL_VAR", "default_val")
	if valMissing != "default_val" {
		t.Errorf("Expected 'default_val', got '%s'", valMissing)
	}
}

func TestValidatePort(t *testing.T) {
	if err := ValidatePort("8080"); err != nil {
		t.Errorf("Expected valid port '8080', got error: %v", err)
	}
	if err := ValidatePort("not-a-port"); err == nil {
		t.Errorf("Expected error for 'not-a-port', got nil")
	}
	if err := ValidatePort("70000"); err == nil {
		t.Errorf("Expected error for '70000' (out of range), got nil")
	}
}
