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
	"fmt"
	"log"

	pubsub "cloud.google.com/go/pubsub/v2/apiv1"
	"cloud.google.com/go/pubsub/v2/apiv1/pubsubpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// PubSubDrainer drains backlogged messages from PubSub subscriptions
// by seeking them to "now". Used during environment reset on GCP.
type PubSubDrainer interface {
	Drain(ctx context.Context) (int, error)
}

// NoOpDrainer is used when PubSub drain is not configured (local dev / emulator).
type NoOpDrainer struct{}

// Drain is a no-op, returning 0 drained subscriptions.
func (d *NoOpDrainer) Drain(ctx context.Context) (int, error) {
	return 0, nil
}

// GCPPubSubDrainer seeks configured subscriptions to the current time,
// effectively discarding all backlogged messages.
type GCPPubSubDrainer struct {
	projectID     string
	subscriptions []string
}

// NewGCPPubSubDrainer creates a drainer for the given project and subscriptions.
func NewGCPPubSubDrainer(projectID string, subscriptions []string) *GCPPubSubDrainer {
	return &GCPPubSubDrainer{
		projectID:     projectID,
		subscriptions: subscriptions,
	}
}

// newSubscriptionAdminClient is the function used to create PubSub admin clients.
// It is a variable to allow replacement in tests.
var newSubscriptionAdminClient = func(ctx context.Context) (*pubsub.SubscriptionAdminClient, error) {
	return pubsub.NewSubscriptionAdminClient(ctx)
}

// Drain seeks all configured subscriptions to "now", discarding backlogged
// messages. Returns the number of subscriptions successfully drained.
func (d *GCPPubSubDrainer) Drain(ctx context.Context) (int, error) {
	if len(d.subscriptions) == 0 {
		return 0, nil
	}

	client, err := newSubscriptionAdminClient(ctx)
	if err != nil {
		return 0, fmt.Errorf("creating pubsub subscriber client: %w", err)
	}
	defer client.Close()

	drained := 0
	var lastErr error
	for _, subName := range d.subscriptions {
		subPath := fmt.Sprintf("projects/%s/subscriptions/%s", d.projectID, subName)
		_, err := client.Seek(ctx, &pubsubpb.SeekRequest{
			Subscription: subPath,
			Target:       &pubsubpb.SeekRequest_Time{Time: timestamppb.Now()},
		})
		if err != nil {
			log.Printf("PubSubDrainer: failed to seek %s: %v", subName, err)
			lastErr = err
			continue
		}
		log.Printf("PubSubDrainer: drained subscription %s", subName)
		drained++
	}

	if lastErr != nil && drained == 0 {
		return 0, fmt.Errorf("all subscription seeks failed, last: %w", lastErr)
	}
	return drained, nil
}
