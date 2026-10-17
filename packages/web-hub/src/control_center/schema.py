"""SQLite schema for durable Stage-1 control-plane artifacts."""


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS control_settings (
        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
        mode TEXT NOT NULL DEFAULT 'guided', paused INTEGER NOT NULL DEFAULT 0,
        pause_reason TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_recommendations (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, title TEXT NOT NULL,
        summary TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'human', risk_level TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'new', disposition_reason TEXT NOT NULL DEFAULT '',
        dedupe_key TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_campaigns (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, recommendation_id TEXT,
        title TEXT NOT NULL, goal TEXT NOT NULL, non_goals TEXT NOT NULL DEFAULT '',
        risk_level TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'draft',
        version INTEGER NOT NULL DEFAULT 1, approved_version INTEGER,
        base_sha TEXT NOT NULL DEFAULT '', approved_sha TEXT NOT NULL DEFAULT '',
        approved_by TEXT NOT NULL DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(recommendation_id) REFERENCES control_recommendations(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_pr_candidates (
        id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, title TEXT NOT NULL,
        scope TEXT NOT NULL, acceptance_criteria_json TEXT NOT NULL,
        non_goals TEXT NOT NULL DEFAULT '', risk_level TEXT NOT NULL DEFAULT 'medium',
        priority INTEGER NOT NULL DEFAULT 100, status TEXT NOT NULL DEFAULT 'ready',
        base_sha TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_pr_dependencies (
        candidate_id TEXT NOT NULL, depends_on_id TEXT NOT NULL,
        PRIMARY KEY(candidate_id, depends_on_id),
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE,
        FOREIGN KEY(depends_on_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE,
        CHECK(candidate_id <> depends_on_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_work_orders (
        id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'approved', approval_sha TEXT NOT NULL,
        approved_by TEXT NOT NULL, rationale TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_attention_items (
        id TEXT PRIMARY KEY, project_id INTEGER, category TEXT NOT NULL,
        entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, title TEXT NOT NULL,
        consequence TEXT NOT NULL DEFAULT '', recommendation TEXT NOT NULL DEFAULT '',
        urgency TEXT NOT NULL DEFAULT 'normal', status TEXT NOT NULL DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_checkpoints (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL, actor TEXT NOT NULL, summary TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
        entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL,
        actor TEXT NOT NULL, from_state TEXT NOT NULL DEFAULT '',
        to_state TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_idempotency (
        idempotency_key TEXT PRIMARY KEY, operation TEXT NOT NULL,
        response_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_repository_policies (
        project_id INTEGER PRIMARY KEY,
        activation_policy TEXT NOT NULL DEFAULT 'per_candidate',
        max_parallel_tasks INTEGER NOT NULL DEFAULT 2,
        max_open_prs INTEGER NOT NULL DEFAULT 8,
        max_candidates INTEGER NOT NULL DEFAULT 100,
        max_retry_attempts INTEGER NOT NULL DEFAULT 3,
        no_progress_limit INTEGER NOT NULL DEFAULT 3,
        lease_seconds INTEGER NOT NULL DEFAULT 900,
        protected_paths_json TEXT NOT NULL DEFAULT '[]',
        required_checks_json TEXT NOT NULL DEFAULT '[]',
        deployment_json TEXT NOT NULL DEFAULT '{}',
        capability_json TEXT NOT NULL DEFAULT '{}',
        merge_strategy TEXT NOT NULL DEFAULT 'squash',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_idea_seeds (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, title TEXT NOT NULL,
        note TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'human',
        status TEXT NOT NULL DEFAULT 'inbox', provenance_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_artifacts (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, campaign_id TEXT,
        artifact_type TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
        supersedes_id TEXT, relative_path TEXT NOT NULL DEFAULT '',
        content_text TEXT NOT NULL DEFAULT '', content_sha256 TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        materialization_status TEXT NOT NULL DEFAULT 'unknown',
        materialized_sha256 TEXT NOT NULL DEFAULT '',
        materialized_commit_sha TEXT NOT NULL DEFAULT '',
        materialized_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, artifact_type, slug, version),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE SET NULL,
        FOREIGN KEY(supersedes_id) REFERENCES control_artifacts(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_idea_seed_artifacts (
        idea_seed_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(idea_seed_id, artifact_id, relation_type),
        FOREIGN KEY(idea_seed_id) REFERENCES control_idea_seeds(id) ON DELETE CASCADE,
        FOREIGN KEY(artifact_id) REFERENCES control_artifacts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_artifact_relations (
        source_artifact_id TEXT NOT NULL, target_artifact_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(source_artifact_id, target_artifact_id, relation_type),
        FOREIGN KEY(source_artifact_id) REFERENCES control_artifacts(id) ON DELETE CASCADE,
        FOREIGN KEY(target_artifact_id) REFERENCES control_artifacts(id) ON DELETE CASCADE,
        CHECK(source_artifact_id <> target_artifact_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_candidate_artifacts (
        candidate_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(candidate_id, artifact_id, relation_type),
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE,
        FOREIGN KEY(artifact_id) REFERENCES control_artifacts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_question_ledger (
        id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, branch TEXT NOT NULL,
        planning_job_id TEXT, amendment_id TEXT,
        content_hash TEXT NOT NULL DEFAULT '',
        question TEXT NOT NULL, rationale TEXT NOT NULL DEFAULT '',
        answer TEXT NOT NULL DEFAULT '', answer_source TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open', owner TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}', contradiction_of TEXT,
        resolved_in_version INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY(contradiction_of) REFERENCES control_question_ledger(id) ON DELETE SET NULL,
        FOREIGN KEY(planning_job_id) REFERENCES control_planning_jobs(id) ON DELETE CASCADE,
        FOREIGN KEY(amendment_id) REFERENCES control_plan_amendments(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_campaign_profiles (
        campaign_id TEXT PRIMARY KEY, slug TEXT NOT NULL,
        planning_depth TEXT NOT NULL DEFAULT 'balanced',
        requested_max_candidates INTEGER NOT NULL DEFAULT 12,
        activation_policy TEXT NOT NULL DEFAULT 'per_candidate',
        readiness_status TEXT NOT NULL DEFAULT 'draft',
        readiness_score REAL NOT NULL DEFAULT 0,
        pivotal_fork TEXT NOT NULL DEFAULT '',
        pivotal_fork_na_reason TEXT NOT NULL DEFAULT '',
        success_metrics_json TEXT NOT NULL DEFAULT '[]',
        constraints_json TEXT NOT NULL DEFAULT '[]',
        assumptions_json TEXT NOT NULL DEFAULT '[]',
        acceptance_matrix_json TEXT NOT NULL DEFAULT '[]',
        alternatives_json TEXT NOT NULL DEFAULT '[]',
        review_strategy TEXT NOT NULL DEFAULT '',
        rollout_plan TEXT NOT NULL DEFAULT '',
        rollback_plan TEXT NOT NULL DEFAULT '',
        repository_map_artifact_id TEXT,
        design_artifact_id TEXT,
        plan_simulation_artifact_id TEXT,
        plan_signature TEXT NOT NULL DEFAULT '',
        current_wave INTEGER NOT NULL DEFAULT 0,
        estimated_cost REAL NOT NULL DEFAULT 0,
        actual_cost REAL NOT NULL DEFAULT 0,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_planning_jobs (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, idea_seed_id TEXT,
        job_type TEXT NOT NULL DEFAULT 'initial_plan', amendment_id TEXT,
        status TEXT NOT NULL DEFAULT 'queued', planning_depth TEXT NOT NULL,
        max_candidates INTEGER NOT NULL, activation_policy TEXT NOT NULL,
        wish TEXT NOT NULL, constraints_json TEXT NOT NULL DEFAULT '[]',
        antigravity_chat_id TEXT NOT NULL DEFAULT '', campaign_id TEXT,
        waiting_reason TEXT NOT NULL DEFAULT '', active_question_id TEXT,
        round_number INTEGER NOT NULL DEFAULT 0,
        attempt INTEGER NOT NULL DEFAULT 0, output_json TEXT NOT NULL DEFAULT '{}',
        last_error TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT 'human',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP, finished_at TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(idea_seed_id) REFERENCES control_idea_seeds(id) ON DELETE SET NULL,
        FOREIGN KEY(amendment_id) REFERENCES control_plan_amendments(id) ON DELETE CASCADE,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE SET NULL,
        FOREIGN KEY(active_question_id) REFERENCES control_question_ledger(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_candidate_contracts (
        candidate_id TEXT PRIMARY KEY, purpose TEXT NOT NULL DEFAULT '',
        components_json TEXT NOT NULL DEFAULT '[]',
        expected_diff_type TEXT NOT NULL DEFAULT 'code',
        required_checks_json TEXT NOT NULL DEFAULT '[]',
        manual_tests_json TEXT NOT NULL DEFAULT '[]',
        reversibility TEXT NOT NULL DEFAULT '',
        migration_plan TEXT NOT NULL DEFAULT '',
        compatibility_plan TEXT NOT NULL DEFAULT '',
        documentation_json TEXT NOT NULL DEFAULT '[]',
        definition_of_done TEXT NOT NULL DEFAULT '',
        estimated_size TEXT NOT NULL DEFAULT 'small',
        business_value REAL NOT NULL DEFAULT 0,
        unblock_score REAL NOT NULL DEFAULT 0,
        learning_value REAL NOT NULL DEFAULT 0,
        urgency_score REAL NOT NULL DEFAULT 0,
        effort_score REAL NOT NULL DEFAULT 1,
        change_risk_score REAL NOT NULL DEFAULT 1,
        reversibility_score REAL NOT NULL DEFAULT 1,
        ready_score REAL NOT NULL DEFAULT 0,
        wave INTEGER NOT NULL DEFAULT 0,
        pinned INTEGER NOT NULL DEFAULT 0,
        paused INTEGER NOT NULL DEFAULT 0,
        override_reason TEXT NOT NULL DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_candidate_conflicts (
        candidate_id TEXT NOT NULL, conflicts_with_id TEXT NOT NULL,
        reason TEXT NOT NULL, resources_json TEXT NOT NULL DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(candidate_id, conflicts_with_id),
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE,
        FOREIGN KEY(conflicts_with_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE,
        CHECK(candidate_id <> conflicts_with_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_plan_amendments (
        id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, from_version INTEGER NOT NULL,
        proposed_version INTEGER NOT NULL, reason TEXT NOT NULL, impact_json TEXT NOT NULL,
        focus_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'proposed', proposed_by TEXT NOT NULL,
        prior_campaign_status TEXT NOT NULL DEFAULT '',
        from_base_sha TEXT NOT NULL DEFAULT '', planning_base_sha TEXT NOT NULL DEFAULT '',
        from_plan_signature TEXT NOT NULL DEFAULT '',
        from_signature_version INTEGER NOT NULL DEFAULT 0,
        before_plan_json TEXT NOT NULL DEFAULT '{}',
        before_plan_sha256 TEXT NOT NULL DEFAULT '',
        target_plan_json TEXT NOT NULL DEFAULT '{}',
        target_plan_sha256 TEXT NOT NULL DEFAULT '',
        patch_json TEXT NOT NULL DEFAULT '{}', patch_sha256 TEXT NOT NULL DEFAULT '',
        validation_json TEXT NOT NULL DEFAULT '{}', planning_job_id TEXT,
        approved_by TEXT NOT NULL DEFAULT '', approved_sha TEXT NOT NULL DEFAULT '',
        resolved_by TEXT NOT NULL DEFAULT '', decision_reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY(planning_job_id) REFERENCES control_planning_jobs(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_agent_tasks (
        id TEXT PRIMARY KEY, work_order_id TEXT NOT NULL UNIQUE,
        project_id INTEGER NOT NULL, campaign_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'implementation',
        status TEXT NOT NULL DEFAULT 'queued', wake_reason TEXT NOT NULL DEFAULT 'work_order',
        base_sha TEXT NOT NULL, current_sha TEXT NOT NULL DEFAULT '',
        merged_sha TEXT NOT NULL DEFAULT '',
        branch_name TEXT NOT NULL, worktree_path TEXT NOT NULL DEFAULT '',
        antigravity_chat_id TEXT NOT NULL DEFAULT '',
        issue_number INTEGER, issue_url TEXT NOT NULL DEFAULT '',
        pr_number INTEGER, pr_url TEXT NOT NULL DEFAULT '',
        lease_owner TEXT NOT NULL DEFAULT '', lease_token TEXT NOT NULL DEFAULT '',
        lease_until TIMESTAMP, attempt INTEGER NOT NULL DEFAULT 0,
        no_progress_count INTEGER NOT NULL DEFAULT 0,
        last_progress_hash TEXT NOT NULL DEFAULT '',
        budget_tokens INTEGER NOT NULL DEFAULT 0,
        budget_seconds INTEGER NOT NULL DEFAULT 3600,
        consumed_tokens INTEGER NOT NULL DEFAULT 0,
        allowed_actions_json TEXT NOT NULL DEFAULT '[]',
        protected_paths_json TEXT NOT NULL DEFAULT '[]',
        last_checkpoint_id TEXT, last_error TEXT NOT NULL DEFAULT '',
        wake_at TIMESTAMP, started_at TIMESTAMP, finished_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(work_order_id) REFERENCES control_work_orders(id) ON DELETE CASCADE,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_task_events (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL, event_type TEXT NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, processed_at TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES control_agent_tasks(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_findings (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL, classification TEXT NOT NULL,
        source TEXT NOT NULL, external_id TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
        resolution TEXT NOT NULL DEFAULT '', sha TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES control_agent_tasks(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_evidence_packs (
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE, project_id INTEGER NOT NULL,
        candidate_id TEXT NOT NULL, sha TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'collecting', summary TEXT NOT NULL DEFAULT '',
        preview_url TEXT NOT NULL DEFAULT '', rollback_plan TEXT NOT NULL DEFAULT '',
        risk_json TEXT NOT NULL DEFAULT '{}', test_pack_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES control_agent_tasks(id) ON DELETE CASCADE,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(candidate_id) REFERENCES control_pr_candidates(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_evidence_items (
        id TEXT PRIMARY KEY, evidence_pack_id TEXT NOT NULL, kind TEXT NOT NULL,
        criterion_key TEXT NOT NULL DEFAULT '', title TEXT NOT NULL,
        status TEXT NOT NULL, sha TEXT NOT NULL, command TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '', artifact_ref TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(evidence_pack_id) REFERENCES control_evidence_packs(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_human_approvals (
        id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL, approval_type TEXT NOT NULL, sha TEXT NOT NULL,
        decision TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, revoked_at TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_deployments (
        id TEXT PRIMARY KEY, task_id TEXT, project_id INTEGER NOT NULL,
        environment TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',
        sha TEXT NOT NULL, artifact_ref TEXT NOT NULL DEFAULT '',
        previous_stable_sha TEXT NOT NULL DEFAULT '', migration_json TEXT NOT NULL DEFAULT '{}',
        logs_json TEXT NOT NULL DEFAULT '[]', health_json TEXT NOT NULL DEFAULT '{}',
        approved_by TEXT NOT NULL DEFAULT '', rollback_of TEXT,
        started_at TIMESTAMP, finished_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES control_agent_tasks(id) ON DELETE SET NULL,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(rollback_of) REFERENCES control_deployments(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_webhook_events (
        delivery_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
        action TEXT NOT NULL DEFAULT '', repository TEXT NOT NULL,
        entity_id TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, processed_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS control_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
        campaign_id TEXT, task_id TEXT, metric TEXT NOT NULL,
        value REAL NOT NULL, unit TEXT NOT NULL DEFAULT 'count',
        labels_json TEXT NOT NULL DEFAULT '{}',
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY(task_id) REFERENCES control_agent_tasks(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_control_recommendations_project ON control_recommendations(project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_control_campaigns_project ON control_campaigns(project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_control_attention_project ON control_attention_items(project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_control_audit_project ON control_audit_events(project_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_control_artifacts_project ON control_artifacts(project_id, artifact_type, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_control_idea_seed_artifacts_artifact ON control_idea_seed_artifacts(artifact_id, relation_type, idea_seed_id)",
    "CREATE INDEX IF NOT EXISTS idx_control_artifact_relations_target ON control_artifact_relations(target_artifact_id, relation_type, source_artifact_id)",
    "CREATE INDEX IF NOT EXISTS idx_control_candidate_artifacts_artifact ON control_candidate_artifacts(artifact_id, relation_type, candidate_id)",
    "CREATE INDEX IF NOT EXISTS idx_control_questions_campaign ON control_question_ledger(campaign_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_control_planning_jobs_status ON control_planning_jobs(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_control_amendments_campaign ON control_plan_amendments(campaign_id, status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_control_tasks_status ON control_agent_tasks(status, wake_at, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_control_tasks_project ON control_agent_tasks(project_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_control_task_events_status ON control_task_events(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_control_findings_task ON control_findings(task_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_control_evidence_task ON control_evidence_items(evidence_pack_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_control_approvals_entity ON control_human_approvals(entity_type, entity_id, approval_type, revoked_at)",
    "CREATE INDEX IF NOT EXISTS idx_control_deployments_project ON control_deployments(project_id, environment, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_control_metrics_campaign ON control_metrics(campaign_id, metric, recorded_at DESC)",
]


def _rebuild_planning_jobs_for_amendments(conn) -> None:
    """Make idea_seed_id nullable without losing legacy planning sessions."""
    columns = {
        str(row["name"]): row
        for row in conn.execute("PRAGMA table_info(control_planning_jobs)")
    }
    idea_seed = columns.get("idea_seed_id")
    needs_rebuild = bool(idea_seed and int(idea_seed["notnull"]) == 1)
    if not needs_rebuild:
        for column_name, definition in (
            ("job_type", "TEXT NOT NULL DEFAULT 'initial_plan'"),
            ("amendment_id", "TEXT"),
        ):
            if column_name not in columns:
                conn.execute(
                    f"ALTER TABLE control_planning_jobs "
                    f"ADD COLUMN {column_name} {definition}"
                )
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TABLE IF EXISTS control_planning_jobs_new")
        conn.execute(
            """CREATE TABLE control_planning_jobs_new (
                   id TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
                   idea_seed_id TEXT,
                   job_type TEXT NOT NULL DEFAULT 'initial_plan', amendment_id TEXT,
                   status TEXT NOT NULL DEFAULT 'queued',
                   planning_depth TEXT NOT NULL, max_candidates INTEGER NOT NULL,
                   activation_policy TEXT NOT NULL, wish TEXT NOT NULL,
                   constraints_json TEXT NOT NULL DEFAULT '[]',
                   antigravity_chat_id TEXT NOT NULL DEFAULT '', campaign_id TEXT,
                   waiting_reason TEXT NOT NULL DEFAULT '', active_question_id TEXT,
                   round_number INTEGER NOT NULL DEFAULT 0,
                   attempt INTEGER NOT NULL DEFAULT 0,
                   output_json TEXT NOT NULL DEFAULT '{}',
                   last_error TEXT NOT NULL DEFAULT '',
                   created_by TEXT NOT NULL DEFAULT 'human',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   started_at TIMESTAMP, finished_at TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                   FOREIGN KEY(idea_seed_id) REFERENCES control_idea_seeds(id) ON DELETE SET NULL,
                   FOREIGN KEY(amendment_id) REFERENCES control_plan_amendments(id) ON DELETE CASCADE,
                   FOREIGN KEY(campaign_id) REFERENCES control_campaigns(id) ON DELETE SET NULL,
                   FOREIGN KEY(active_question_id) REFERENCES control_question_ledger(id) ON DELETE SET NULL
               )"""
        )
        source_columns = set(columns)
        target_columns = [
            "id", "project_id", "idea_seed_id", "job_type", "amendment_id",
            "status", "planning_depth", "max_candidates", "activation_policy",
            "wish", "constraints_json", "antigravity_chat_id", "campaign_id",
            "waiting_reason", "active_question_id", "round_number", "attempt",
            "output_json", "last_error", "created_by", "created_at",
            "started_at", "finished_at", "updated_at",
        ]
        select_expressions = []
        for column_name in target_columns:
            if column_name in source_columns:
                select_expressions.append(column_name)
            elif column_name == "job_type":
                select_expressions.append("'initial_plan' AS job_type")
            elif column_name == "amendment_id":
                select_expressions.append("NULL AS amendment_id")
            elif column_name == "waiting_reason":
                select_expressions.append("'' AS waiting_reason")
            elif column_name == "active_question_id":
                select_expressions.append("NULL AS active_question_id")
            elif column_name == "round_number":
                select_expressions.append("0 AS round_number")
            else:  # pragma: no cover - guarded by every supported legacy shape
                raise RuntimeError(
                    f"Unsupported planning-job migration column: {column_name}"
                )
        conn.execute(
            "INSERT INTO control_planning_jobs_new ("
            + ", ".join(target_columns)
            + ") SELECT "
            + ", ".join(select_expressions)
            + " FROM control_planning_jobs"
        )
        conn.execute("DROP TABLE control_planning_jobs")
        conn.execute(
            "ALTER TABLE control_planning_jobs_new RENAME TO control_planning_jobs"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_schema(database) -> None:
    with database._get_connection() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        _rebuild_planning_jobs_for_amendments(conn)
        conn.execute(
            """UPDATE control_attention_items
               SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
               WHERE category = 'agent_permission' AND status = 'open'
                 AND id NOT IN (
                     SELECT MIN(id)
                     FROM control_attention_items
                     WHERE category = 'agent_permission' AND status = 'open'
                     GROUP BY entity_type, entity_id, category
                 )"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS
               idx_control_attention_unique_open_agent_permission
               ON control_attention_items(entity_type, entity_id, category)
               WHERE status = 'open' AND category = 'agent_permission'"""
        )
        artifact_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(control_artifacts)").fetchall()
        }
        for column_name, definition in (
            ("materialization_status", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("materialized_sha256", "TEXT NOT NULL DEFAULT ''"),
            ("materialized_commit_sha", "TEXT NOT NULL DEFAULT ''"),
            ("materialized_at", "TIMESTAMP"),
        ):
            if column_name not in artifact_columns:
                conn.execute(
                    f"ALTER TABLE control_artifacts "
                    f"ADD COLUMN {column_name} {definition}"
                )
        task_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(control_agent_tasks)").fetchall()
        }
        if "merged_sha" not in task_columns:
            conn.execute(
                """ALTER TABLE control_agent_tasks
                   ADD COLUMN merged_sha TEXT NOT NULL DEFAULT ''"""
            )
        planning_job_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(control_planning_jobs)"
            ).fetchall()
        }
        for column_name, definition in (
            ("waiting_reason", "TEXT NOT NULL DEFAULT ''"),
            ("active_question_id", "TEXT"),
            ("round_number", "INTEGER NOT NULL DEFAULT 0"),
            ("job_type", "TEXT NOT NULL DEFAULT 'initial_plan'"),
            ("amendment_id", "TEXT"),
        ):
            if column_name not in planning_job_columns:
                conn.execute(
                    f"ALTER TABLE control_planning_jobs "
                    f"ADD COLUMN {column_name} {definition}"
                )
        question_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(control_question_ledger)"
            ).fetchall()
        }
        for column_name, definition in (
            ("planning_job_id", "TEXT"),
            ("amendment_id", "TEXT"),
            ("content_hash", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column_name not in question_columns:
                conn.execute(
                    f"ALTER TABLE control_question_ledger "
                    f"ADD COLUMN {column_name} {definition}"
                )
        amendment_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(control_plan_amendments)"
            ).fetchall()
        }
        for column_name, definition in (
            ("focus_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("prior_campaign_status", "TEXT NOT NULL DEFAULT ''"),
            ("from_base_sha", "TEXT NOT NULL DEFAULT ''"),
            ("planning_base_sha", "TEXT NOT NULL DEFAULT ''"),
            ("from_plan_signature", "TEXT NOT NULL DEFAULT ''"),
            ("from_signature_version", "INTEGER NOT NULL DEFAULT 0"),
            ("before_plan_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("before_plan_sha256", "TEXT NOT NULL DEFAULT ''"),
            ("target_plan_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("target_plan_sha256", "TEXT NOT NULL DEFAULT ''"),
            ("patch_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("patch_sha256", "TEXT NOT NULL DEFAULT ''"),
            ("validation_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("planning_job_id", "TEXT"),
            ("resolved_by", "TEXT NOT NULL DEFAULT ''"),
            ("decision_reason", "TEXT NOT NULL DEFAULT ''"),
            ("updated_at", "TIMESTAMP"),
        ):
            if column_name not in amendment_columns:
                conn.execute(
                    f"ALTER TABLE control_plan_amendments "
                    f"ADD COLUMN {column_name} {definition}"
                )
        conn.execute(
            """UPDATE control_plan_amendments
               SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"""
        )
        profile_columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(control_campaign_profiles)"
            ).fetchall()
        }
        for column_name, definition in (
            ("alternatives_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("review_strategy", "TEXT NOT NULL DEFAULT ''"),
            ("pivotal_fork_na_reason", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column_name not in profile_columns:
                conn.execute(
                    f"ALTER TABLE control_campaign_profiles "
                    f"ADD COLUMN {column_name} {definition}"
                )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS
               idx_control_questions_unique_session_content
               ON control_question_ledger(planning_job_id, content_hash)
               WHERE planning_job_id IS NOT NULL AND content_hash <> ''"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_control_planning_jobs_status
               ON control_planning_jobs(status, created_at)"""
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_control_planning_jobs_amendment
               ON control_planning_jobs(amendment_id, status)"""
        )
        conn.execute(
            """UPDATE control_plan_amendments AS amendment
               SET status = 'cancelled',
                   resolved_by = CASE WHEN resolved_by = ''
                       THEN 'schema_migration' ELSE resolved_by END,
                   decision_reason = CASE WHEN decision_reason = ''
                       THEN 'Superseded by a newer open amendment during migration.'
                       ELSE decision_reason END,
                   resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP),
                   updated_at = CURRENT_TIMESTAMP
               WHERE amendment.status IN ('planning', 'review', 'failed', 'proposed')
                 AND EXISTS (
                     SELECT 1 FROM control_plan_amendments AS newer
                     WHERE newer.campaign_id = amendment.campaign_id
                       AND newer.status IN ('planning', 'review', 'failed', 'proposed')
                       AND (
                           COALESCE(newer.created_at, '')
                               > COALESCE(amendment.created_at, '')
                           OR (
                               COALESCE(newer.created_at, '')
                                   = COALESCE(amendment.created_at, '')
                               AND newer.rowid > amendment.rowid
                           )
                       )
                 )"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_control_amendment_unique_open
               ON control_plan_amendments(campaign_id)
               WHERE status IN ('planning', 'review', 'failed', 'proposed')"""
        )
        conn.execute(
            """UPDATE control_planning_jobs
               SET status = 'completed', waiting_reason = '',
                   active_question_id = NULL,
                   finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                   updated_at = CURRENT_TIMESTAMP
               WHERE status = 'waiting_human'
                 AND campaign_id IN (
                     SELECT id FROM control_campaigns
                     WHERE status IN ('approved', 'active', 'completed')
                 )"""
        )
        conn.execute(
            """UPDATE control_planning_jobs
               SET status = 'cancelled', waiting_reason = '',
                   active_question_id = NULL,
                   finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
                   updated_at = CURRENT_TIMESTAMP
               WHERE status = 'waiting_human'
                 AND campaign_id IN (
                     SELECT id FROM control_campaigns
                     WHERE status = 'cancelled'
                 )"""
        )
        conn.execute(
            """UPDATE control_planning_jobs
               SET waiting_reason = 'plan_approval'
               WHERE status = 'waiting_human' AND campaign_id IS NOT NULL
                 AND waiting_reason = ''"""
        )
        conn.execute(
            "INSERT OR IGNORE INTO control_settings (singleton_id, mode, paused) VALUES (1, 'guided', 0)"
        )
        conn.execute(
            """INSERT OR IGNORE INTO control_campaign_profiles (
                   campaign_id, slug, planning_depth, requested_max_candidates
               )
               SELECT id, lower(replace(title, ' ', '-')), 'compact', 5
               FROM control_campaigns"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO control_candidate_contracts (
                   candidate_id, purpose, required_checks_json,
                   definition_of_done
               )
               SELECT id, scope, '["Repository-Testbefehl erfolgreich"]',
                      acceptance_criteria_json
               FROM control_pr_candidates"""
        )
        conn.commit()
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(
                "Control-center schema migration left invalid foreign keys."
            )
