/* Simplified controller logic excerpt */
const config = require('../input/config/robot-config.json');
let disconnectTimer = null;

function sendHeartbeat() {
  // ... transport send here ...
}

function onHeartbeatTimeout() {
  // Trigger disconnect handling if no heartbeat ack was received in time
  // (actual disconnect logic omitted)
}

function startHeartbeat() {
  // Periodic heartbeat as configured
  setInterval(sendHeartbeat, config.network.heartbeatIntervalMs);
}

function scheduleDisconnectTimeout() {
  // Schedules a timeout to treat missing heartbeats as fatal
  if (disconnectTimer) clearTimeout(disconnectTimer);
  disconnectTimer = setTimeout(onHeartbeatTimeout, config.network.disconnectAfterMs);
}

module.exports = {
  startHeartbeat,
  scheduleDisconnectTimeout
};