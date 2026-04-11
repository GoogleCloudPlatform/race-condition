// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package hub

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNoOpDrainer_DrainReturnsZero(t *testing.T) {
	d := &NoOpDrainer{}
	count, err := d.Drain(context.Background())
	assert.NoError(t, err)
	assert.Equal(t, 0, count)
}

func TestGCPPubSubDrainer_EmptySubscriptions(t *testing.T) {
	d := NewGCPPubSubDrainer("test-project", nil)
	count, err := d.Drain(context.Background())
	assert.NoError(t, err)
	assert.Equal(t, 0, count)
}
