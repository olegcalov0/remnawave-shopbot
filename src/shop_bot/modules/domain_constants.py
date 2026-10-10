"""Строгие enum-константы статусов и типов нового домена (Этап 1, п.5 ТЗ).

Запрещено использовать произвольные строки в разных файлах.
"""
from __future__ import annotations

from typing import Literal

# ===== traffic types =====
TrafficType = Literal["wifi", "lte"]
TRAFFIC_TYPE_WIFI: TrafficType = "wifi"
TRAFFIC_TYPE_LTE: TrafficType = "lte"
TRAFFIC_TYPES = (TRAFFIC_TYPE_WIFI, TRAFFIC_TYPE_LTE)

TargetRole = Literal["primary", "hybrid"]
ROLE_PRIMARY: TargetRole = "primary"
ROLE_HYBRID: TargetRole = "hybrid"
TARGET_ROLES = (ROLE_PRIMARY, ROLE_HYBRID)


def traffic_type_for_role(role: TargetRole) -> TrafficType:
    """wifi -> primary, lte -> hybrid (инвариант 3.2.2)."""
    return TRAFFIC_TYPE_LTE if role == ROLE_HYBRID else TRAFFIC_TYPE_WIFI


def role_for_traffic_type(traffic_type: TrafficType) -> TargetRole:
    return ROLE_HYBRID if traffic_type == TRAFFIC_TYPE_LTE else ROLE_PRIMARY

# ===== pair statuses =====
PairStatus = Literal["active", "repair_required", "broken", "detached", "deleted"]
PAIR_ACTIVE: PairStatus = "active"
PAIR_REPAIR_REQUIRED: PairStatus = "repair_required"
PAIR_BROKEN: PairStatus = "broken"
PAIR_DETACHED: PairStatus = "detached"
PAIR_DELETED: PairStatus = "deleted"

# ===== traffic_purchases.status =====
PurchaseStatus = Literal[
    "created", "payment_pending", "paid", "fulfilling", "fulfilled",
    "retryable_failure", "manual_review", "cancelled",
]
PURCHASE_CREATED: PurchaseStatus = "created"
PURCHASE_PAYMENT_PENDING: PurchaseStatus = "payment_pending"
PURCHASE_PAID: PurchaseStatus = "paid"
PURCHASE_FULFILLING: PurchaseStatus = "fulfilling"
PURCHASE_FULFILLED: PurchaseStatus = "fulfilled"
PURCHASE_RETRYABLE_FAILURE: PurchaseStatus = "retryable_failure"
PURCHASE_MANUAL_REVIEW: PurchaseStatus = "manual_review"
PURCHASE_CANCELLED: PurchaseStatus = "cancelled"

# ===== payment_fulfillment_jobs.status =====
JobStatus = Literal["paid", "processing", "retryable_failure", "fulfilled", "manual_review"]
JOB_PAID: JobStatus = "paid"
JOB_PROCESSING: JobStatus = "processing"
JOB_RETRYABLE_FAILURE: JobStatus = "retryable_failure"
JOB_FULFILLED: JobStatus = "fulfilled"
JOB_MANUAL_REVIEW: JobStatus = "manual_review"

# ===== traffic_operations =====
OperationType = Literal[
    "purchase_credit", "referral_credit", "manual_adjustment",
    "monthly_reset", "expiry_burn", "hybrid_repair", "hwid_sync",
]
OP_PURCHASE_CREDIT: OperationType = "purchase_credit"
OP_REFERRAL_CREDIT: OperationType = "referral_credit"
OP_MANUAL_ADJUSTMENT: OperationType = "manual_adjustment"
OP_MONTHLY_RESET: OperationType = "monthly_reset"
OP_EXPIRY_BURN: OperationType = "expiry_burn"
OP_HYBRID_REPAIR: OperationType = "hybrid_repair"
OP_HWID_SYNC: OperationType = "hwid_sync"

OperationResult = Literal["pending", "success", "failed", "skipped"]
OP_RESULT_PENDING: OperationResult = "pending"
OP_RESULT_SUCCESS: OperationResult = "success"
OP_RESULT_FAILED: OperationResult = "failed"
OP_RESULT_SKIPPED: OperationResult = "skipped"

ActorType = Literal["user", "admin", "automation", "system"]
ACTOR_USER: ActorType = "user"
ACTOR_ADMIN: ActorType = "admin"
ACTOR_AUTOMATION: ActorType = "automation"
ACTOR_SYSTEM: ActorType = "system"

# ===== traffic_referral_rewards.status =====
RewardStatus = Literal["pending", "fulfilled", "failed", "manual_review"]
REWARD_PENDING: RewardStatus = "pending"
REWARD_FULFILLED: RewardStatus = "fulfilled"
REWARD_FAILED: RewardStatus = "failed"
REWARD_MANUAL_REVIEW: RewardStatus = "manual_review"

# ===== pending_transactions.status (мин. pending|paid|failed) =====
PendingTxStatus = Literal["pending", "paid", "failed"]
PENDING_TX_PENDING: PendingTxStatus = "pending"
PENDING_TX_PAID: PendingTxStatus = "paid"
PENDING_TX_FAILED: PendingTxStatus = "failed"

# ===== backup =====
BackupSource = Literal["scheduled", "manual"]
BACKUP_SOURCE_SCHEDULED: BackupSource = "scheduled"
BACKUP_SOURCE_MANUAL: BackupSource = "manual"

SnapshotStatus = Literal["running", "complete", "incomplete", "failed"]
SNAPSHOT_RUNNING: SnapshotStatus = "running"
SNAPSHOT_COMPLETE: SnapshotStatus = "complete"
SNAPSHOT_INCOMPLETE: SnapshotStatus = "incomplete"
SNAPSHOT_FAILED: SnapshotStatus = "failed"

# ===== schema version =====
SCHEMA_VERSION_KEY = "schema_version"
SCHEMA_VERSION_CURRENT = "2"
SCHEMA_VERSION_MIN_SUPPORTED = "2"
