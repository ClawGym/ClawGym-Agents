JIRA: PAY-1427 — SEPA Credit Transfer (pacs.008) Outbound Interface

Summary
Our core banking system will submit outbound SEPA Credit Transfer instructions as ISO 20022 pacs.008 messages to FTM over MQ. FTM must process, validate/map to ISF v3, orchestrate via a Transaction FSM, and deliver the payment to the SEPA clearinghouse over HTTP. Operator alerting and timeout handling are required. This follows the standard FTM design methodology: DESIGN (RSAD) → BUILD (ACE) → DEPLOY (DB2 config + BARs) → OPERATE (OAC).

Business Context
- Scheme: SEPA Credit Transfer (SCT)
- Message: pacs.008 (ISO 20022)
- Direction: Outbound (core system → FTM → clearinghouse)
- Volumes: ~150k/day, peak 5k/hour
- SLA: Clearinghouse acknowledgement expected within 2 hours; otherwise raise an operator alert
- Error handling: Mapping failures and delivery errors must raise OAC-visible alerts with operator Constraints

Pattern & Object Model
- Applicable FTM Pattern: Pattern 9.1 (Outbound Message/File). Justification: single outbound message flow — receive from core → map → create transaction → send to external network (HTTP) with ack/timeout handling.
- Object type: TRANSACTION
- Proposed SUBTYPE: SEPA_OUTBOUND_TXN (unique per outbound SEPA flow)
- FSM: Custom transaction FSM or registration of subtype to generic outbound transaction FSM if entirely standard; design should include timeout and error alert paths

Transports & Endpoints
- PT Flow ingress (from core): MQ
  - PT input queue: CORE.SEPA.OUTBOUND.IN
- EP/Event queue: FTM.EVENTS.DEFAULT
- Outbound delivery: HTTP POST to clearinghouse endpoint
  - Endpoint (non-prod): https://api.sct-clearing.sbx.example.com/v1/payments
  - Endpoint (prod): https://api.sct-clearing.eu/v1/payments
  - HTTP headers: Content-Type: application/xml; Accept: application/xml
  - TLS: 1.2+, mutual TLS (client cert); 10s connect timeout, 30s response timeout
  - Expected response: 202 Accepted with a correlation/reference ID in Location header

Timeouts & Alerts
- ACK SLA: 2 hours from send time. If no correlated ack/confirmation by SLA, raise TIMEOUT alert.
- Timeout detection: Using E_Heartbeat event every ~60 seconds with an Object Filter guard comparing TIMEOUT (timestamp) < CURRENT TIMESTAMP.
- Alert policies:
  - Mapping error alert: operator Constraints = Cancel, Resubmit
  - Timeout alert: operator Constraints = Cancel, Continue
  - Send failure alert (HTTP non-2xx): operator Constraints = Cancel, Resubmit

Events (standard where possible)
- E_MpInMappingComplete — PT flow after mapping success
- E_MpInMappingAborted — PT flow after mapping failure
- E_TxnOutCreated — Action after creating outbound txn
- E_TransOutSent — Action after HTTP send success
- E_Heartbeat — periodic for timeout check
- Optional custom: E_ClearingAckReceived when ack correlates to the transaction (if implemented)

Mapping & ISF
- Mapping technology: Prefer ESQL for XML→ISF field-by-field mapping; aligns with team skills and maintainability for ISO 20022 pacs.008.
- ISF namespace: http://www.ibm.com/xmlns/prod/ftm/isf/v3
- Mapper subflow name (convention): MapInPacs008
- Required ISF population (non-exhaustive): Debtor, Creditor, Debtor/Creditor accounts (IBAN), Instructed amount (with currency attribute), RemittanceInformation
- Reference fields provided in input/isf_fields.csv

Service Participant & Channel (proposed)
- SP name: CLEARING_SEPA_OUTBOUND
  - Type: CLEARINGHOUSE
  - Role: CREDITOR_AGENT
  - Status: ACTIVE (INACTIVE until go-live in lower envs)
- Channel name: CLEARING_SEPA_HTTP_OUT
  - Direction: OUTBOUND
  - Format: ISO20022_pacs.008
  - Transport: HTTP
  - Endpoint: as above (env-specific)
  - Mapper subflow (PT side): MapInPacs008

Action Subflow Naming (suggested)
- ActValidateAndRoute
- ActCreateTxn
- ActSendHttpPayment
- ActHandleAck
- ActRaiseMappingAlert
- ActRaiseSendAlert
- ActTimeoutAlert
- ActCancel
- ActResubmit

Acceptance Criteria
- RSAD artifacts (7): Use case, functional sequence, FSM, SP/Channel config, service interaction, deployment topology, SQL export scripts
- FSM has: PMP_Alert states with Constraints on all error paths, heartbeat-based timeout transition with guard on CURRENT TIMESTAMP, PMP_Terminal final states (COMPLETED/CANCELLED)
- SUBTYPE = SEPA_OUTBOUND_TXN with OBJECT_SELECTION_TEMPLATE to match
- SQL exports for SP, Channel, FSM ready for DB2 import
- Mapping matrix (pacs.008 → ISF) delivered with handling of amount and currency attributes

Notes
- Party codes and naming conventions are provided in input/party_codes.csv
- Non-functional constraints in input/constraints.yaml
- ISF field references in input/isf_fields.csv