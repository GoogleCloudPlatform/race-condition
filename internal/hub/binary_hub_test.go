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
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestBinaryHubDelivery(t *testing.T) {
	hub := NewHub()
	go hub.Run()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		hub.Register("sess-binary-1", conn)
	}))
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer conn.Close()

	// Wait for registration
	time.Sleep(100 * time.Millisecond)

	testMsg := &gateway.Wrapper{
		Type:        "json",
		Status:      "success",
		Event:       "zonal_event",
		SessionId:   "sess-binary-1",
		Destination: []string{"sess-binary-1"},
		Payload:     []byte(`{"msg": "zonal block here"}`),
	}

	hub.HandleRemoteMessage(testMsg)

	// Verify client receives Protobuf Wrapper
	messageType, dataBytes, err := conn.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, websocket.BinaryMessage, messageType)

	var received gateway.Wrapper
	err = proto.Unmarshal(dataBytes, &received)
	require.NoError(t, err)

	assert.Equal(t, "json", received.Type)
	assert.Equal(t, "success", received.Status)
	assert.Equal(t, "zonal_event", received.Event)
	assert.ElementsMatch(t, []string{"sess-binary-1"}, received.Destination)

	var dataMap map[string]interface{}
	err = json.Unmarshal(received.Payload, &dataMap)
	require.NoError(t, err)
	assert.Equal(t, "zonal block here", dataMap["msg"])
}
