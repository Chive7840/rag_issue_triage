"""
Deterministic synthetic GitHub/Jira issue generation.

- No external deps. Requires only stdlib.
- Emits .ndjson (optionally gzipped) or prints JSON lines to stdout.
- Tunable vis CLI args; stable via seed.

Usage example -- GitHub:
``python generate_deterministic_sample.py --flavor github -n 750 --seed demo-42 --days 30 -o ../../db/sandbox/github_issues.ndjson``

Usage example -- Jira:
``python generate_deterministic_sample.py --flavor jira   -n 750  --seed demo-42 --days 30 -o ../../db/sandbox/jira_issues.ndjson``

    Optional:
        Add `.gz` after `.ndjson` at the end of each command to compress the data.
"""

from __future__ import annotations
import argparse, gzip, json, math, sys, os, random, re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from api.services.paraphrase_engine import (
    BaseParaphraser,
    LockedEntityGuard,
    ProviderRegistry,
)


# ----------- github repo name generator -----------
orgs = ["hirokawa", "tanaka", "aoyama", "nishinoen", "yoshida", "nagisa",
        "rizzi-coppola", "montanari", "sartori-group", "cattaneo", "bianchi"]
services = ["auth", "billing", "search", "orders", "metrics", "notifications",
            "ai-engineering", "data-solutions", "data-analysis", "app-building"]
suffixes = ["api", "service", "worker", "frontend", "backend", "cli", "full-stack",
            "databases"]
stacks = ["node", "react", "go", "python", "spark", "c++", "docker", "rust"]
fun = ["octo", "quantum", "rusty", "neon", "plasma"]
others = ["sushi", "penguin", "train", "llama", "grass", "ink"]

def gen_repo(rng: random.Random):
    """Generate a synthetic repository name using weighted templates."""

    pattern = rng.choice([1,2,3,4,5])
    if pattern == 1:
        return f"{rng.choice(orgs)}-{rng.choice(suffixes)}"
    if pattern == 2:  # service + suffix
        return f"{rng.choice(services)}-{rng.choice(suffixes)}"
    if pattern == 3:  # feature + stack
        return f"{rng.choice(services)}-{rng.choice(stacks)}"
    if pattern == 4:  # infra/exp
        return f"{rng.choice(['infra','exp'])}-{rng.choice(services)}"
    if pattern == 5:  # fun style
        return f"{rng.choice(fun)}-{rng.choice(others)}"


def gen_repos(n: int, seed: int = 42) -> list[str]:
    """Return ``n`` unique-ish repository slugs for sampling fixtures."""

    rng = random.Random(seed)
    repo_list = list({gen_repo(rng) for _ in range(n*2)})[:n] # oversample then dedupe
    return repo_list


# ----------- compact config -----------
repos = gen_repos(15)
CONFIG = {
    "repos": repos,
    "project_keys": [
        "CORE","INFRA","ITSM","OPS","DEV","DEVOPS","PLATFORM","API","WEB","MOBILE","BACKEND","FRONTEND",
        "SERVICE","ADMIN","QA","TEST","UXP","RND","RAG","RISK","SECURITY","AUTH","PAY","BILL","CMS","CRM",
        "ERP","DATA","ANALYTICS","ML","AI","SEARCH","NOTIF","INTEG","LOGS","AUDIT","MIGRATE","MIG","SUPPORT",
        "HELP","DOCS","TRAIN","REF","CONFIG","SERVICES","PLUGINS","EXT","EMBED","SDK","LIB","TOOLS","SCHED",
        "BATCH","JOBS","QUEUE","PROD","STAGE","TESTING","DEMO","POC","ERR","MONITOR","ALERT","SEC","PRIV",
        "COMPLIANCE","DEFAULT","ACME"
    ],
    "components": ["users", "payments", "searches", "APIs", "servers", "notifications", "alerts", "analytics",
                   "metrics", "emails", "databases", "files", "integrations", "external services", "configurations",
                   "errors", "carts"],
    "users": ["maria", "nushi", "mohammed", "jose", "wei", "yan", "john", "carlos",
              "aleksandr", "ping", "anita", "ram"],
    "labels": ["type: bug", "type: discussion", "type: epic", "type: feature request", "type: question",
               "type: documentation", "type: enhancement", "status: can't reproduce", "status: confirmed",
               "status: duplicate", "status: needs information", "status: wont do/fix", "priority: critical",
               "priority: high", "priority: low", "priority: medium", "help wanted", "good first issue"],
    "issue_types_github": ["Bug Report", "Feature Request", "Task", "Documentation issue", "Needs more info",
                           "Enhancement", "Duplicate", "Help wanted", "Good first issue", "Invalid", "Won't fix"],
    "issue_types_jira": ["Epic", "Story", "Task", "Bug", "Sub-Task", "Incident", "Problem", "Change",
                         "Service Request", "Service Request (Approved)"],
    "hourly_weight": [2,1,1,1,1,1,2,4,6,8,9,8,7,7,7,8,9,8,6,5,4,3,3,2],
    "p_duplicate": 0.06,
    "p_burst": 0.35,
    "templates": [
        "{component}: {verb} {object} when {condition}",
        "[{scope}] {component} fails on {env} with {error_class} ({code})",
        "{component} {verb_past} after {action} in {env}",
        "Regression: {object} {verb} on {branch} since {version}"
    ],
    "lex": {
        "component": ["authentication", "user", "payment", "search", "API", "server", "frontend", "UX",
                      "notification", "alert", "reporting", "analytic", "metric", "logging", "audit",
                      "tracing", "caching", "performance", "email", "storage", "database", "file", "security",
                      "SSL", "integration", "external services", "admin", "configuration", "testing", "QA", "CI",
                      "error", "crash handling", "internationalization", "localization", "cart", "documentation",
                      "sorting", "scheduler", "filtering", "persistence"],

        "verb": [
            "fail","crash","hang","deadlock","panic","time_out","freeze","skip","drop","misroute","stall","block",
            "lock_up","leak","corrupt","overflow","underflow","reject","deny","miscalculate","misalign","misorder",
            "duplicate","lose","mismatch","stutter","flicker","flash","delay","lag","throttle","glitch","blur","jam",
            "malfunction","break","disconnect","reset","lock","lock_out","cant_connect","cannot_connect","err","error",
            "throw_exception","deny_access","invalidate","sanitize","reject_input","accept_invalid","overrun",
            "underutilize","starve","bog_down","stall_on","buffer","overload","thrash","sync_fail","async_fail",
            "parallel_fail","semaphore_fail"
        ],

        "verb_past": [
            "failed","crashed","hung","deadlocked","panicked","timed_out","froze","skipped","dropped","misrouted",
            "stalled","blocked","locked_up","leaked","corrupted","overflowed","underflowed","rejected","denied",
            "miscalculated","misaligned","misordered","duplicated","lost","mismatched","stuttered","flickered","flashed",
            "delayed","lagged","throttled","glitched","blurred","jammed","malfunctioned","broke","disconnected","reset",
            "locked","locked_out","could_not_connect","errored","threw_exception","denied_access","invalidated",
            "sanitized","rejected_input","accepted_invalid","overran","underutilized","starved","bogged_down","stalled_on",
            "buffered","overloaded","thrashed","synced_failed","async_failed","parallel_failed","semaphore_failed"
        ],

        "object": [
            "OAuth_flow","pagination","retry_logic","session_management","token_refresh","rate_limiting","caching_layer",
            "database_connection","query_builder","data_model","API_endpoint","webhook_handler","file_upload","file_download",
            "image_processing","video_streaming","search_index","full_text_search","filtering","sorting","paging",
            "cursor_pagination","offset_pagination","cursor_logic","authentication","authorization","permission_check",
            "user_profile","user_registration","user_settings","password_reset","two_factor_auth","email_verification",
            "session_timeout","session_store","token_storage","logging_system","audit_trail","error_handler",
            "exception_middleware","monitoring","metrics_collector","alerting","dashboard","background_job","cron_scheduler",
            "task_queue","worker_process","notification_service","email_sender","sms_service","push_notifications",
            "payment_gateway","subscription_service","billing_cycle","invoice_generation","refund_process",
            "subscription_cancellation","reporting_module","analytics_pipeline","data_aggregation","data_export","data_import",
            "CSV_import","JSON_export","integration_adapter","third_party_API","webhook_consumer","cache_eviction",
            "cache_invalidation","CDN_integration","static_assets","file_storage","media_transcoding","thumbnail_generation",
            "search_autocomplete","spellcheck","language_translation","i18n","localization","time_zone_handling",
            "rate_limiter","circuit_breaker","bulk_batch_job","pagination_cursor","schema_migration","database_migration",
            "ORM_layer","transaction_manager","locking_mechanism","concurrency_control","mutex_lock","semaphore_logic",
            "deadlock_detector","queue_manager","message_broker","pubsub_channel","event_emitter","state_machine",
            "workflow_engine","feature_flag","toggle_system","config_loader","settings_page","admin_dashboard",
            "security_module","encryption_engine","token_encryption","SSL_certificate","TLS_handshake","rate_limit_headers",
            "session_cookie","CSRF_protection","XSS_sanitization","input_validation","schema_validation","form_handler",
            "bulk_import","bulk_export","REST_controller","GraphQL_resolver","gRPC_endpoint","API_client","SDK_wrapper",
            "library_module","utility_functions","helper_methods","templating_engine","UI_component","frontend_router",
            "client_state","virtual_dom","CSS_styles","theme_manager","accessibility_layer"
        ],

        "condition": [  # unchanged; high-signal and already normalized
            "token_expired","token_revoked","token_missing","invalid_token","token_scope_insufficient","unauthorized",
            "forbidden","not_found","conflict_state","precondition_failed","rate_limit_reached","quota_exceeded","throttled",
            "backoff_in_effect","burst_detected","cold_start","warm_start","container_recycled","pod_evicted",
            "rolling_deploy_in_progress","network_jitter","packet_loss","high_latency","connection_reset",
            "connection_refused","dns_failure","tls_handshake_failed","certificate_expired","certificate_mismatch",
            "mtu_mismatch","zero_results","empty_response","partial_response","stale_data","inconsistent_data",
            "large_payload","payload_too_small","payload_malformed","payload_truncated","unsupported_media_type",
            "timeout_read","timeout_write","timeout_connect","timeout_request","deadline_exceeded","cache_miss",
            "cache_stale","cache_eviction","cache_thrash","cache_poisoned","db_connection_pool_exhausted",
            "db_lock_contention","deadlock_detected","serialization_conflict","replica_lag_high","disk_full",
            "inode_exhausted","read_only_filesystem","slow_io","io_error","memory_pressure","oom_killed","gc_pause_long",
            "heap_fragmentation","swap_thrashing","cpu_starvation","cpu_throttled","hot_spin","priority_inversion",
            "runqueue_saturated","thread_leak","goroutine_leak","file_descriptor_leak","socket_leak","handle_leak",
            "feature_flag_disabled","feature_flag_misconfigured","flag_dependency_missing","flag_variation_unknown",
            "flag_evaluation_failed","config_missing","config_invalid","config_out_of_range","config_unreadable",
            "config_reload_failed","schema_mismatch","migration_pending","migration_failed","index_missing",
            "index_corrupted","duplicate_key","foreign_key_violation","constraint_violation","null_constraint_breach",
            "unique_index_conflict","clock_skew","time_sync_failed","token_not_yet_valid","signature_expired",
            "nonce_reuse_detected","csrf_token_invalid","xss_detected","open_redirect_detected","ssrf_blocked",
            "cors_blocked","insufficient_permissions","role_missing","ownership_mismatch","policy_denied",
            "iam_misconfigured","dependency_unavailable","upstream_degraded","third_party_timeout","webhook_failure",
            "sdk_version_incompatible","unsupported_api_version","deprecated_endpoint","breaking_change_detected",
            "contract_violation","protobuf_mismatch","retry_exhausted","idempotency_key_conflict",
            "duplicate_request_detected","circuit_open","circuit_half_open","queue_backlog_high","consumer_lag_high",
            "message_poisoned","dlq_growing","ordering_violation","batch_too_large","batch_too_small","window_missed",
            "schedule_drift","cron_misfire","cold_cache","warm_cache","hot_partition","skewed_traffic",
            "imbalance_detected","mobile_backgrounded","app_killed_by_os","low_battery_mode","no_network_access",
            "roaming_restricted","browser_unsupported","third_party_cookie_blocked","adblock_interference",
            "storage_quota_exceeded","private_mode_limited","render_timeout","layout_shift_excessive","webgl_unavailable",
            "gpu_driver_bug","font_load_failed","ab_test_mismatch","variant_not_assigned","experiment_paused",
            "metric_window_empty","guardrail_breached","pii_redaction_failed","data_masking_incomplete",
            "encryption_key_rotated","kms_unavailable","hsm_error","audit_log_unwritable","log_rate_limited",
            "log_format_invalid","trace_context_missing","span_dropped","geo_restriction","region_unavailable","az_outage",
            "failover_in_progress","multi_region_inconsistency","manual_override_active","maintenance_window_active",
            "read_only_mode","degraded_mode","safe_mode_enabled","sandbox_restriction","entitlement_missing",
            "license_expired","seat_limit_reached","trial_expired","payment_declined","card_expired","avs_mismatch",
            "3ds_challenge_required","invoice_overdue","user_disabled","account_locked","mfa_required",
            "mfa_challenge_failed","password_expired","input_validation_failed","field_missing","field_out_of_range",
            "regex_mismatch","enum_value_unknown","graph_cycle_detected","topology_change_pending","shard_unavailable",
            "rebalance_in_progress","split_brain_detected"
        ],

        "scope": [
            "api","ui","frontend","backend","infra","documentation","metrics","telemetry","logging","security","auth",
            "authorization","authentication","db","database","storage","media","network","proxy","cache","caching",
            "integration","third_party","webhook","sdk","cli","mobile","desktop","web","service","microservice","monolith",
            "pipeline","ci","cd","deployment","ops","platform","monitoring","alerting","observability","reporting","search",
            "index","queue","messaging","pubsub","batch","worker","scheduler","cron","task","job","queue_consumer",
            "file_system","filesystem","storage_io","cache_eviction","load_balancer","api_gateway","proxy_server",
            "networking","dns","tls","ssl","certificate","schema","migration","orm","versioning","compatibility",
            "feature_flag","flags","toggle","configuration","settings","theme","ux","ui_component","layout","css","styling",
            "accessibility","i18n","localization","l10n","timezone","session","token","cookie","csrf","cors","validation",
            "rate_limit","throttling","error","exception","timeout","performance","optimization","profiling","scaling",
            "availability","reliability","resilience","fault_tolerance","failover","backup","restore","replication",
            "storage_cluster","sharding","partitioning","consistency","replica","leader_election","consensus","raft",
            "persistence","memory","cpu","disk","io","network_io","gpu","cache_hit","cache_miss","hotspot","bottleneck"
        ],

        "env": [
            "Chrome_126","Chrome_127","Firefox_118","Firefox_119","Safari_17","Safari_18","Edge_126","Edge_127",
            "iOS_17","iOS_18","Android_14","Android_15","Windows_10","Windows_11","Windows_Server_2019",
            "Windows_Server_2022","Ubuntu_22.04","Ubuntu_20.04","Debian_12","Debian_11","Fedora_38","Fedora_39",
            "CentOS_8","CentOS_Stream_9","RedHat_8","RedHat_9","MacOS_Ventura","MacOS_Monterey","MacOS_Sonoma",
            "Node_18","Node_20","Node_22","Python_3.10","Python_3.11","Python_3.12","Java_11","Java_17","Java_21",
            "DotNet_6","DotNet_7","DotNet_8","Go_1.20","Go_1.21","Rust_1.70","Rust_1.71","Ruby_3.1","Ruby_3.2",
            "PHP_8.1","PHP_8.2","Docker_24","Docker_25","Kubernetes_1.27","Kubernetes_1.28","AWS_Lambda_Node20",
            "AWS_Lambda_Python311","AWS_EC2_Ubuntu2204","Azure_Functions_dotNet8","GCP_Cloud_Run_Container",
            "Heroku_22_Stack","Netlify_22","Vercel_Node20","iPadOS_17","iPadOS_18","tvOS_17","watchOS_10",
            "ChromeOS_146","FireOS_8","Tizen_7","KaiOS_3","Oracle_Linux_9","SUSE_Enterprise_15","OpenSUSE_Leap_15",
            "FreeBSD_14","Alpine_Linux_3.18"
        ],

        "error_class": [
            "NullPointerException","IndexOutOfBoundsException","ArrayIndexOutOfBoundsException","ClassCastException",
            "IllegalArgumentException","IllegalStateException","ArithmeticException","OverflowException",
            "UnderflowException","NumberFormatException","FormatException","ParseException","IOException",
            "FileNotFoundException","EOFException","SocketException","BindException","ConnectException",
            "UnknownHostException","SSLHandshakeException","CertificateException","KeyManagementException",
            "NoSuchAlgorithmException","InvalidKeyException","SignatureException","KeyStoreException",
            "UnsupportedEncodingException","TimeoutException","ReadTimeoutException","WriteTimeoutException",
            "ConnectionTimeoutException","CancellationException","InterruptedException","ExecutionException",
            "TimeoutError","RuntimeError","ValueError","TypeError","KeyError","IndexError","AttributeError",
            "ImportError","ModuleNotFoundError","NameError","UnboundLocalError","ZeroDivisionError","OverflowError",
            "MemoryError","RecursionError","AssertionError","NotImplementedError","PermissionError","OSError",
            "BlockingIOError","BrokenPipeError","ConnectionRefusedError","ConnectionResetError","ConnectionAbortedError",
            "SSLZeroReturnError","SSLError","ProtocolError","ProtocolException","URISyntaxException",
            "MalformedURLException","HTTPException","HttpResponseException","BadRequestException",
            "UnauthorizedException","ForbiddenException","NotFoundException","ConflictException",
            "ServiceUnavailableException","InternalServerErrorException","GatewayTimeoutException",
            "BadGatewayException","TooManyRequestsException","GrpcUnavailable","GrpcDeadlineExceeded","GrpcInternal",
            "GrpcCancelled","GrpcResourceExhausted","GrpcUnimplemented","GrpcUnauthenticated","GrpcAborted",
            "GrpcDataLoss","GrpcUnknown","DatabaseException","SQLException","DataIntegrityViolationException",
            "ConstraintViolationException","DuplicateKeyException","EntityNotFoundException",
            "OptimisticLockingFailureException","StaleStateException","TransactionRollbackException",
            "DeadlockDetectedException","CacheException","CacheMissException","CacheEvictionException",
            "SerializationException","DeserializationException","JsonParseException","JsonMappingException",
            "XmlParseException","XmlStreamException","ProtobufParseException","GrpcParseException",
            "ValidationException","ConstraintViolationError","SchemaValidationException","IllegalStateError",
            "IllegalAccessException","SecurityException","AccessDeniedException","AuthenticationException",
            "UnauthorizedAccessException","NetworkError","ConnectionError","ResponseError","ResponseTimeout",
            "SocketTimeoutException","HttpRequestException","HttpTimeoutException","HttpProtocolException",
            "ApiException","ServiceException","ClientException","ServerException","ResourceNotFoundException",
            "ResourceUnavailableException","FeatureDisabledException","UnsupportedOperationException",
            "UnsupportedVersionException","DeprecatedEndpointException","VersionMismatchException",
            "BusinessLogicException","DomainException","ApplicationException","IntegrationException",
            "ThirdPartyException","WebhookException","ConcurrencyException","SynchronizationException",
            "LockAcquisitionException","InterruptedIOException","StreamClosedException","EndOfStreamException",
            "InsufficientPermissionsException","RoleNotFoundException","PolicyViolationException"
        ],

        "code": [
            "400","401","403","404","405","406","408","409","410","411","412","413","414","415","416","417","418",
            "429","451","500","501","502","503","504","505",
            "ECONNRESET","ECONNREFUSED","ETIMEDOUT","EHOSTUNREACH","ENETUNREACH","EPIPE","EADDRINUSE","EADDRNOTAVAIL",
            "EIO","EBADF","EAGAIN","EEXIST","ENOENT","ENOMEM","ENOSPC","EINVAL","EPERM","EACCES","EISDIR","ENOTDIR",
            "ELOOP","EROFS","EXDEV","ESPIPE","ENOTEMPTY","ECANCELED","EINTR","EFBIG","EMFILE","ENFILE","ENOTCONN",
            "ESHUTDOWN","EALREADY","EDESTADDRREQ","ENETDOWN","ENETRESET","ENOBUFS","ENOTSOCK","EOPNOTSUPP",
            "EPROTONOSUPPORT",
            "SIGSEGV","SIGABRT","SIGBUS","SIGILL","SIGFPE","SIGTERM","SIGKILL","SIGINT","SIGHUP","SIGPIPE","SIGTRAP",
            "SIGCHLD",
            "ERR_AUTH_401","ERR_AUTH_EXPIRED","ERR_AUTH_REVOKED","ERR_FORBIDDEN_403","ERR_NOT_FOUND_404",
            "ERR_CONFLICT_409","ERR_RATE_LIMIT","ERR_THROTTLED","ERR_INTERNAL_500","ERR_UNAVAILABLE_503",
            "ERR_GATEWAY_TIMEOUT_504","ERR_SERVICE_DOWN","ERR_DB_CONN","ERR_DB_TIMEOUT","ERR_DB_DEADLOCK",
            "ERR_TXN_ROLLBACK","ERR_CACHE_MISS","ERR_CACHE_TIMEOUT","ERR_QUEUE_BACKPRESSURE","ERR_QUEUE_FULL",
            "ERR_QUEUE_EMPTY","ERR_API_DEPRECATED","ERR_API_VERSION_UNSUPPORTED","ERR_SCHEMA_MISMATCH",
            "ERR_SERIALIZATION","ERR_DESERIALIZATION","ERR_VALIDATION_FAILED","ERR_INVALID_ARGUMENT",
            "ERR_INVALID_STATE","ERR_INVALID_TYPE","ERR_INVALID_RESPONSE","ERR_MALFORMED_REQUEST",
            "ERR_UNSUPPORTED_OPERATION","ERR_UNSUPPORTED_MEDIA_TYPE","ERR_UNEXPECTED_TOKEN","ERR_TIMEOUT",
            "ERR_OPERATION_ABORTED","ERR_RETRY_EXHAUSTED","ERR_PERMISSION_DENIED","ERR_ACCESS_VIOLATION",
            "ERR_NOT_IMPLEMENTED","ERR_NOT_INITIALIZED","ERR_DEPENDENCY_UNAVAILABLE","ERR_FEATURE_FLAG_DISABLED",
            "ERR_LICENSE_EXPIRED","ERR_LIMIT_EXCEEDED","ERR_QUOTA_EXCEEDED","ERR_TOKEN_EXPIRED","ERR_TOKEN_INVALID",
            "ERR_TOKEN_MISSING","ERR_TOKEN_SCOPE","ERR_CSRF","ERR_SIGNATURE_INVALID","ERR_SSL_HANDSHAKE",
            "ERR_TLS_CERT","ERR_CERT_EXPIRED","ERR_ENCRYPTION_FAILED","ERR_DECRYPTION_FAILED","ERR_UNDERFLOW",
            "ERR_OVERFLOW","ERR_DIVIDE_BY_ZERO","ERR_MEMORY_LEAK","ERR_STACK_OVERFLOW","ERR_BUFFER_OVERFLOW",
            "ERR_INDEX_OUT_OF_BOUNDS","ERR_KEY_NOT_FOUND","ERR_DUPLICATE_KEY","ERR_FILE_NOT_FOUND",
            "ERR_FILE_TOO_LARGE","ERR_DISK_FULL","ERR_NETWORK_JITTER","ERR_NETWORK_TIMEOUT","ERR_NETWORK_UNAVAILABLE",
            "ERR_DNS_FAILURE","ERR_PROXY_UNREACHABLE","ERR_LOAD_BALANCER_TIMEOUT","ERR_RATE_LIMITED",
            "ERR_API_QUOTA_EXCEEDED","ERR_CLIENT_ABORTED","ERR_SERVER_BUSY","ERR_SERVICE_DEGRADED",
            "ERR_UNHEALTHY_DEPENDENCY","ERR_PLUGIN_FAILURE","ERR_MIGRATION_FAILED","ERR_VERSION_CONFLICT",
            "ERR_STATE_DESYNC","ERR_REPLICATION_LAG","ERR_DATA_CORRUPTION","ERR_EVENT_LOOP_BLOCKED","ERR_GC_PAUSE",
            "ERR_OOM_KILLED","ERR_COLD_START","ERR_CONTAINER_EVICTED","ERR_POD_RESTARTED"
        ],

        "action": [
            "deploy","rollback","hotfix_deploy","patch","rebuild","redeploy","restart_service","restart_instance","scale_up",
            "scale_down","increase_capacity","reduce_capacity","add_replica","remove_replica","drain_node","evacuate_node",
            "retry","exponential_backoff_retry","retry_later","retry_now","fail_fast","fallback_to_cache","fallback_to_static",
            "serve_stale","serve_placeholder","serve_default","serve_error_page","redirect","redirect_to_safe",
            "redirect_to_login","redirect_to_https","rate_limit_response","throttle_client","reject_request","queue_request",
            "deferred_execution","queue_message","enqueue_retry","requeue","dead_letter","send_to_dlq","pause_processing",
            "resume_processing","open_circuit","close_circuit","half_open_circuit","feature_flag_toggle_on",
            "feature_flag_toggle_off","feature_flag_rollout","disable_feature_flag","enable_feature_flag","canary_rollout",
            "blue_green_deploy","blue_green_switch","stop_canary","promote_canary","rollback_canary","migrate_schema",
            "rollback_schema","apply_migration","revert_migration","run_migration","baseline_migration","data_migration",
            "index_rebuild","index_recreate","reindex","vacuum_db","compact_db","archive_old_data","purge_old_logs",
            "cleanup_temp_files","cleanup_cache","invalidate_cache","clear_cache","warm_cache","preload_cache",
            "cache_warmup","cache_rebuild","cache_evict","cache_flush","reconnect_db","reset_db_connection",
            "open_new_connection","close_connection","refresh_token","rotate_token","invalidate_token","reissue_token",
            "revoke_token","resend_email","resend_verification","notify_admin","alert_team","send_alert",
            "create_incident_ticket","auto_heal","self_heal","failover","promote_secondary","switch_to_backup","switch_over",
            "activate_backup","deactivate_primary","start_backup","restore_from_backup","rolling_restart","rolling_update",
            "restart_cluster","shrink_cluster","expand_cluster","rebalance_shard","reshard","resync_replica","catchup_replica",
            "repair_replica","snapshot_restore","snapshot_backup","snapshot_create","snapshot_delete","trim_logs",
            "rotate_logs","compress_logs","upload_logs","enable_monitoring","disable_monitoring","escalate_issue",
            "escalate_to_sre","escalate_to_dev","open_support_case","engage_oncall","trigger_alert","dump_stack_trace",
            "collect_diagnostics","upload_diagnostics","enable_debug_logging","disable_debug_logging","increase_log_level",
            "roll_log_files","archive_logs","generate_report","audit_data","validate_data","repair_data","consistency_check",
            "integrity_check","resend_event","republish_event","replay_events","reprocess_queue","throttle_producer",
            "backpressure_propagation","signal_backpressure","cull_requests","drop_requests","reject_requests",
            "gracefully_shutdown","force_shutdown","scale_instances","add_node","remove_node","isolate_faulty_node",
            "quarantine_node","blacklist_node","disable_endpoint","enable_endpoint","block_endpoint","unblock_endpoint",
            "disable_api","enable_api","deprecate_api","purge_old_version","rollout_patch","rollout_fix","rollback_patch"
        ],

        "branch": [
            "main","master","develop","dev","staging","prod","production","release/2025.10","release/2025.11",
            "release/1.0","release/v1.0","release/v2.0","hotfix/auth-401","hotfix/token-expired","hotfix/issue-123",
            "hotfix/critical-bug","hotfix/security-patch","feature/oauth-flow","feature/pagination-improvement",
            "feature/retry-logic","feature/search-index","feature/ui-enhancement","feature/api-versioning",
            "feature/cache-optimization","feature/metrics-dashboard","feature/infra-automation","feature/docker-support",
            "feature/infra-monitoring","feature/login-ui","feature/admin-panel","bugfix/null-pointer",
            "bugfix/crash-on-start","bugfix/search-error","bugfix/memory-leak","bugfix/timeout-handling",
            "bugfix/pagination-bug","experiment/ab-test","experiment/new-ui","spike/db-migration",
            "spike/performance-profiling","chore/deps-update","chore/clean-up","chore/reformat","chore/linting",
            "chore/docs-update","ci/update-pipeline","ci/fix-workflow","ci/add-tests","ops/infra-deploy",
            "ops/monitoring-setup","ops/db-maintenance","refactor/code-cleanup","refactor/module-split",
            "refactor/remove-dead-code","test/new-integration-tests","test/performance-tests","test/load-tests"
        ],

        "version": [
            "v1.0.0","v1.2.5","v2.0.0","v2.3.1","v2.4.0-rc1","v2.4.0-rc2","v2.4.0","v2.5.0-beta","v2.5.1","v3.0.0",
            "v3.1.0","v3.1.1","v3.2.0-alpha","v3.2.0","v3.3.0","v4.0.0","v4.0.1","v4.1.0","2024.09.0","2024.10.0",
            "2024.12.1","2025.01.0","2025.03.0","2025.06.0","2025.08.2","2025.09.0","2025.10.0","2025.10.1"
        ],

        "steps": [
            "Go to settings and enable feature flag","Sign in with test account","Log out and log back in",
            "Clear browser cookies and refresh the page","Call /v1/auth/refresh","Call /v1/users/me endpoint",
            "Trigger background sync from dashboard","Submit form with valid credentials",
            "Submit form with expired token","Open devtools network tab","Inspect console for JavaScript errors",
            "Observe 504 on POST /token","Observe 401 on GET /profile","Inspect response payload for error message",
            "Reproduce in incognito mode","Check retry logic by disconnecting network",
            "Restart the service using systemctl","Deploy branch feature/oauth-flow to staging",
            "Monitor logs with tail -f /var/log/app.log","Run npm test locally","Run pytest -k auth",
            "Restart Docker container for api-gateway","View Grafana dashboard for API latency",
            "Check CloudWatch metrics for Lambda timeout","Run kubectl describe pod <pod-name>",
            "Run kubectl logs <pod-name> --tail=100","Rebuild image with docker build . -t app:latest",
            "Redeploy to staging using CI pipeline","Perform schema migration using prisma migrate deploy",
            "Verify database table users has new column active","Inspect Redis cache with redis-cli keys *",
            "Run GET /v1/health and confirm status 200","Temporarily disable CDN caching",
            "Enable verbose logging in config.yaml","Retry the same request with Authorization header removed",
            "Check DNS resolution using dig api.example.com","Simulate network jitter using tc qdisc add delay 200ms",
            "Test pagination on /v1/items?page=2","Verify JSON schema matches latest OpenAPI spec",
            "Run load test with k6 run loadtest.js","Start local dev server with npm run dev",
            "Reproduce in Chrome 126 and Firefox 118","Recreate environment using docker-compose up",
            "Rollback release/2025.10 to previous version","Invalidate CloudFront cache manually",
            "Restart background worker service","Observe memory usage via htop",
            "Verify authentication cookie is set in response headers","Compare response between staging and production",
            "Run integration tests for payment workflow","Inspect Sentry issue stack trace for error class",
            "Restart Postgres container and check migrations","Run curl -v https://api.example.com/v1/token",
            "Observe intermittent ECONNRESET during retry","Trigger job retry in UI and confirm success",
            "Reproduce using mobile Safari iOS 17","Disable adblock and reload application",
            "Check request headers for Content-Type mismatch","Observe null pointer in backend logs",
            "Compare environment variables between staging and prod","Restart API Gateway to clear stale connections",
            "Run terraform apply for infrastructure changes","Run npm run lint to verify code quality",
            "Observe GraphQL resolver timeout in logs","Test error boundary by forcing exception",
            "Reproduce issue after clearing app cache","Log into admin dashboard and toggle maintenance mode",
            "Review CI build logs for failed test stage","Rollback feature flag rollout to 0%",
            "Run feature flag audit from management console","Restart queue consumer service",
            "Revalidate CDN edge nodes","Observe 503 Service Unavailable in client logs",
            "Rerun failing test case locally to confirm reproduction"
        ],

        "reactions": [":thumbsup:", ":eyes:", ":rocket:", ":bug:"]
    },

    # minimal FSMs
    "fsm_github": {
        "Bug": {
            "Open": [("Triaged", 0.7), ("Closed", 0.1), ("Backlog", 0.2)],
            "Triaged": [("In Progress", 0.6), ("Backlog", 0.3), ("Closed", 0.1)],
            "In Progress": [("Review", 0.6), ("Closed", 0.3), ("Blocked", 0.1)],
            "Review": [("Closed", 0.75), ("Reopened", 0.1), ("In Progress", 0.15)],
            "Blocked": [("In Progress", 0.7), ("Backlog", 0.3)],
            "Backlog": [("Triaged", 0.5), ("Closed", 0.5)],
            "Reopened": [("In Progress", 0.8), ("Backlog", 0.2)],
            "Closed": []
        }
    },
    "fsm_jira": {
        "Bug": {
            "To do": [("In Progress", 0.7), ("Done", 0.05), ("Backlog", 0.25)],
            "In Progress": [("In Review", 0.6), ("Blocked", 0.2), ("Done", 0.2)],
            "In Review": [("Done", 0.75), ("Reopened", 0.15), ("In Progress", 0.1)],
            "Blocked": [("In Progress", 0.7), ("Backlog", 0.3)],
            "Backlog": [("To Do", 1.0)],
            "Reopened": [("In Progress", 0.9), ("Backlog", 0.1)],
            "Done": []
        }
    }
}

PARAPHRASE_FIELDS = {"context", "steps", "expected", "actual", "notes"}

def _word_count(text: str) -> int:
    """Count words in ``text`` using a lightweight regex."""

    return len(re.findall(r"\b\w+\b", text))


# ----------- utils -----------
def wchoice(rng: random.Random, pairs: List[Tuple[str, float]]) -> str:
    """Draw a value from ``pairs`` where the second item is the weight."""

    total = sum(w for _, w in pairs)
    r = rng.random() * total
    for v, w in pairs:
        r -= w
        if r <= 0:
            return v
    return pairs[-1][0]


def poisson_knuth(rng: random.Random, lam: float) -> int:
    """Sample a Poisson-distributed cou t via Knuth's algorithm."""

    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def lognormal(rng: random.Random, mu: float, sigma: float) -> float:
    """Return a log-normal sample using the random generator ``rng``."""

    return math.exp(rng.normalvariate(mu, sigma))


def sample_created_at(rng: random.Random, base: datetime, i: int, hourly_w: List[int], days: int) -> datetime:
    """Spread issues across ``days`` while weighting by hour-of-day."""

    # spread issues over past `days`, weight by hour-of-day
    day = i % days
    hour = wchoice(rng, [(h, w) for h, w in enumerate(hourly_w)])
    minute = rng.randrange(0, 60)
    return base + timedelta(days=day, hours=int(hour), minutes=minute)


def title_from_tpl(rng: random.Random, tpl: str, lex: Dict[str, List[str]]) -> str:
    """Fill ``tpl`` placeholders with random picks from ``lex``."""

    out = tpl
    for key, vals in lex.items():
        token = "{%s}" % key
        if token in out:
            out = out.replace(token, rng.choice(vals))
    return " ".join(out.split())


def body_md(rng: random.Random, lex: Dict[str, List[str]], env: str) -> str:
    """Assemble a mini-markdown body referencing environment ``env``."""

    step_1, step_2 = rng.sample(lex["steps"], k=2)
    expected = "200 OK" if rng.random() < 0.5 else "success toast"
    observed = "504 Gateway Timeout" if rng.random() < 0.5 else "TypeError: undefined"
    return "\n".join([
        "### Environment",
        f"- {env}",
        "",
        "### Steps to Reproduce",
        f"- {step_1}",
        f"- {step_2}",
        "",
        "### Expected",
        f"- {expected}",
        "",
        "### Actual",
        f"- {observed}",
    ])


def walk_fsm(rng: random.Random, flavor: str, issue_type: str, created: datetime) -> Tuple[List[dict], str, datetime]:
    """Simulate workflow transitions for an issue lifecycle."""

    fsm = CONFIG["fsm_github"] if flavor == "github" else CONFIG["fsm_jira"]
    graph = fsm.get(issue_type) or fsm.get("Bug", {})
    start = "Open" if flavor == "github" else "To Do"
    state, t = start, created
    transitions: List[dict] = []
    steps = 1 + min(6, poisson_knuth(rng, 2.0))
    for _ in range(steps):
        outs = graph.get(state, [])
        if not outs:
            break
        to = wchoice(rng, outs)
        dt_min = max(5, int(lognormal(rng, 5.7, 0.8))) # minutes
        t = t + timedelta(minutes=dt_min)
        transitions.append({"from": state, "to": to, "at": t.astimezone(timezone.utc).isoformat()})
        state = to
    last = transitions[-1]["to"] if transitions else start
    return transitions, last, t


def synth_comments(
        rng: random.Random,
        users: List[str],
        created: datetime,
        end_at: datetime,
        p_burst: float,
) -> List[dict] :
    """Create lightweight synthetic comments between ``created`` and ``end_at``."""

    base = poisson_knuth(rng, 0.6)
    extra = (1 + poisson_knuth(rng, 1.2)) if rng.random() < p_burst else 0
    total = min(12, base + extra)
    comments = []
    span = (end_at - created).total_seconds()
    for _ in range(total):
        at = created + timedelta(seconds=int(rng.random() * max(1, span)))
        body = "LGTM" if rng.random() < 0.3 else ("Can you add logs?" if rng.random() < 0.5 else "Repro confirmed.")
        comments.append({
            "id": f"c_{rng.choice(users)}_{rng.randrange(36**6):06x}",
            "author": rng.choice(users),
            "at": at.astimezone(timezone.utc).isoformat(),
            "body": body
        })
    comments.sort(key=lambda c: c["at"])
    return comments

def _apply_paraphrase(
        paraphraser: BaseParaphraser,
        guard: LockedEntityGuard,
        text: Optional[str],
) -> str:
    """Apply paraphrasing while preserving locked entities."""

    if text is None or not text.strip():
        return text or ""
    masked, replacements = guard.mask(text)
    constraints = None
    if replacements:
        constraints = {"do_not_change": [placeholder for placeholder, _ in replacements]}
    result = paraphraser.paraphrase(masked, constraints=constraints)
    return guard.unmask(result.text, replacements)


def synth_issue(
        rng: random.Random,
        i: int,
        flavor: str,
        days_span: int,
        paraphraser: BaseParaphraser,
        guard: LockedEntityGuard,
) -> dict:
    """Produce a deterministic-ish issue payload for ``flavor``."""

    repos = CONFIG["repos"]; projects = CONFIG["project_keys"]
    comps = CONFIG["components"]; users = CONFIG["users"]; labels_all = CONFIG["labels"]
    types = CONFIG["issue_types_github"] if flavor == "github" else CONFIG["issue_types_jira"]
    hourly = CONFIG["hourly_weight"]; lex = CONFIG["lex"]; tpls = CONFIG["templates"]

    repo = rng.choice(repos) if flavor == "github" else None
    project = rng.choice(projects) if flavor == "jira" else None
    component = rng.choice(comps)
    reporter = rng.choice(users)
    assignee = rng.choice([u for u in users if u != reporter]) if rng.random() < 0.9 else None
    labels = list({rng.choice(labels_all) for _ in range (1 + rng.randrange(0, 3))})
    priority = ["P0", "P1", "P2", "P3"][rng.randrange(0, 4)]
    issue_type = rng.choice(types)

    base = datetime.now(timezone.utc) -  timedelta(days=days_span + 5)
    created = sample_created_at(rng, base, i, hourly, days_span)
    tpl = rng.choice(tpls)
    env = rng.choice(lex["env"])
    title = _apply_paraphrase(paraphraser, guard, title_from_tpl(rng, tpl, lex))
    body = _apply_paraphrase(paraphraser, guard, body_md(rng, lex, env))
    version_tag = rng.choice(lex["version"])
    error_class = rng.choice(lex["error_class"])
    file_path = f"services/{component}/handler.py"
    status_url = f"https://status.example.com/{component}"
    inline_toggle = f"{component}_retry"
    steps_selected = rng.sample(lex["steps"], k=2)
    context_section = (
        f"{component} incident observed in {env} after deploying version {version_tag}."
    )
    steps_section = "\n".join(
        f"{idx + 1}. {step}" for idx, step in enumerate(steps_selected)
    )
    expected_section = (
        f"The {component} workflow should return 200 OK without extra retries."
    )
    actual_section = (
        f"{error_class} raised from {file_path} while calling {steps_selected[0].split()[0]}"
        f" and hitting {status_url}."
    )
    notes_section = (
        f"Review `{inline_toggle}` flag output and logs at /var/log/{component}.service. "
        f"See {status_url} for rollout notes in {repo or project or 'sandbox'} and keep"
        f" reference commit pinned."
    )

    transitions, last_state, end_at = walk_fsm(rng, flavor, issue_type, created)
    comments = synth_comments(rng, users, created, end_at, CONFIG["p_burst"])
    for comment in comments:
        comment["body"] = _apply_paraphrase(paraphraser, guard, comment.get("body", ""))
    closed_at = end_at.isoformat() if last_state in ("Closed", "Done") else None

    if rng.random() < CONFIG["p_duplicate"] and "duplicate" not in labels:
        labels.append("duplicate")

    out = {
        "id": f"{flavor}_{rng.randrange(36**10):010x}",
        "number": i + 1,
        "title": title,
        "body": body,
        "type": issue_type,
        "priority": priority,
        "labels": labels,
        "reporter": reporter,
        "assignee": assignee,
        "component": component,
        "repo": repo,
        "projectKey": project,
        "sprint": f"SPR-{1 + rng.randrange(0,20)}" if flavor == "jira" and rng.random() < 0.5 else None,
        "createdAt": created.isoformat(),
        "updatedAt": end_at.isoformat(),
        "closedAt": closed_at,
        "transitions": transitions,
        "comments": comments,
        "context": context_section,
        "steps": steps_section,
        "expected": expected_section,
        "actual": actual_section,
        "notes": notes_section,
    }
    return out

# ----------- cli -----------
def main():
    """Command-line entrypoint for deterministic dataset generation."""

    p = argparse.ArgumentParser(description="Synthesize GitHub/Jira issues")
    p.add_argument("--flavor", choices=["github", "jira"], required=True)
    p.add_argument("-n", "--num", "--count", dest="num", type=int, default=1500)
    p.add_argument("--seed", type=str, default="demo-42")
    p.add_argument("--days", type=int, default=30, help="spread creation over past N days")
    p.add_argument("-o", "--out", type=str, default="-", help="output path (.ndjson or .ndjson.gz")
    p.add_argument(
        "--paraphrase",
        choices=["off", "rule", "hf_local"],
        default="rule",
        help="Paraphrase provided to apply to titles, bodies, and comments.",
    )
    p.add_argument(
        "--paraphrase-budget",
        type=int,
        default=15,
        help="Maximum token edits allowed per section during paraphrasing.",
    )
    default_model = os.getenv("PARAPHRASE_MODEL", "t5-small")
    default_cache = os.getenv("HF_CACHE_DIR", ".cache/hf")
    default_allow = os.getenv("HF_ALLOW_DOWNLOADS", "").lower() in {"1", "true", "yes"}
    p.add_argument(
        "--paraphrase-max-edits-ratio",
        type=float,
        default=0.25,
        help="Maximum fraction of tokens that may change in a section.",
    )
    p.add_argument("--hf-model", type=str, default=None, help="Model name for hf_local provider")
    p.add_argument(
        "--hf-cache",
        type=str,
        default=None,
        help="Cache directory containing Hugging Face models for hf_local",
    )
    p.add_argument(
        "--hf-device",
        type=str,
        default=None,
        help="Device identifier for hf_local paraphraser (e.g. 'cuda:0', 'cpu').",
    )
    p.add_argument(
        "--hf-allow-downloads",
        action="store_true",
        help="Permit hf_local provider to download models if missing locally.",
    )
    args = p.parse_args()

    rng = random.Random(args.seed)
    write_gzip = args.out.endswith(".gz")
    sink = sys.stdout

    guard = LockedEntityGuard()
    paraphraser = ProviderRegistry.get(
        args.paraphrase,
        seed=args.seed,
        paraphrase_budget=args.paraphrase_budget,
        max_edits_ratio=args.paraphrase_max_edits_ratio,
        model_name=args.hf_model,
        cache_dir=args.hf_cache,
        allow_downloads=args.hf_allow_downloads,
        device=args.hf_device,
    )

    if args.out != "-":
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        if write_gzip:
            sink = gzip.open(args.out, "wt", encoding="utf-8")
        else:
            sink = open(args.out, "w", encoding="utf-8")

    try:
        for i in range(args.num):
            rec = synth_issue(rng, i, args.flavor, args.days, paraphraser, guard)
            sink.write(json.dumps(rec, separators=(",",":")) + "\n")
    finally:
        if sink is not sys.stdout:
            sink.close()


if __name__ == "__main__":
    main()
