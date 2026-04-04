import uuid

from max.models.messages import ClarificationRequest, Intent, Priority, Result, StatusUpdate
from max.models.tasks import AuditReport, AuditVerdict, SubTask, Task, TaskStatus


def test_intent_creation():
    intent = Intent(
        user_message="Deploy the app to staging",
        source_platform="telegram",
        goal_anchor="Deploy the app to staging",
    )
    assert intent.user_message == "Deploy the app to staging"
    assert intent.source_platform == "telegram"
    assert intent.goal_anchor == "Deploy the app to staging"
    assert intent.priority == Priority.NORMAL
    assert intent.id is not None


def test_result_creation():
    result = Result(
        task_id=uuid.uuid4(),
        content="Deployment complete. App is live at staging.example.com",
        artifacts=["/logs/deploy.log"],
        confidence=0.95,
    )
    assert result.confidence == 0.95
    assert len(result.artifacts) == 1


def test_clarification_request():
    req = ClarificationRequest(
        task_id=uuid.uuid4(),
        question="Which staging environment — US or EU?",
        options=["US staging", "EU staging"],
    )
    assert len(req.options) == 2


def test_status_update():
    update = StatusUpdate(
        task_id=uuid.uuid4(),
        message="Sub-agent 3/5 completed. Running auditor.",
        progress=0.6,
    )
    assert update.progress == 0.6


def test_task_creation():
    task = Task(
        goal_anchor="Deploy the app to staging",
        source_intent_id=uuid.uuid4(),
    )
    assert task.status == TaskStatus.PENDING
    assert task.subtasks == []
    assert task.created_at is not None


def test_subtask_creation():
    subtask = SubTask(
        parent_task_id=uuid.uuid4(),
        description="Run database migrations",
        assigned_tools=["shell.execute", "git.pull"],
    )
    assert subtask.status == TaskStatus.PENDING
    assert len(subtask.assigned_tools) == 2


def test_audit_report():
    report = AuditReport(
        task_id=uuid.uuid4(),
        subtask_id=uuid.uuid4(),
        verdict=AuditVerdict.PASS,
        score=0.92,
        goal_alignment=0.95,
        confidence=0.88,
        issues=[],
    )
    assert report.verdict == AuditVerdict.PASS
    assert report.issues == []


def test_audit_report_with_issues():
    report = AuditReport(
        task_id=uuid.uuid4(),
        subtask_id=uuid.uuid4(),
        verdict=AuditVerdict.FAIL,
        score=0.4,
        goal_alignment=0.6,
        confidence=0.9,
        issues=[
            {
                "severity": "critical",
                "description": "Missing error handling",
                "suggestion": "Add try/except",
            }
        ],
    )
    assert report.verdict == AuditVerdict.FAIL
    assert len(report.issues) == 1
    assert report.issues[0]["severity"] == "critical"
