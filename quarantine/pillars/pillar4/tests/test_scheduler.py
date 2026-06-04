"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Tests for Scheduler module
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from src.monitoring.scheduler import (
    Scheduler,
    Job,
    Schedule,
    JobStatus,
    JobType,
    ScheduleType,
)


@pytest.fixture
def simple_job():
    def dummy_callback():
        return "job completed"
    
    return Job(
        job_id="",
        name="test_job",
        job_type=JobType.PERIODIC,
        callback=dummy_callback,
        schedule_type=ScheduleType.INTERVAL,
        interval=60.0,
        priority=1
    )


@pytest.fixture
def async_job():
    async def async_callback():
        await asyncio.sleep(0.1)
        return "async job completed"
    
    return Job(
        job_id="",
        name="async_test_job",
        job_type=JobType.PERIODIC,
        callback=async_callback,
        schedule_type=ScheduleType.INTERVAL,
        interval=60.0,
        priority=1
    )


@pytest.fixture
def scheduler():
    return Scheduler(max_workers=2, max_queue_size=100)


class TestJob:
    def test_job_creation(self, simple_job):
        assert simple_job.job_id != ""
        assert simple_job.name == "test_job"
        assert simple_job.job_type == JobType.PERIODIC
        assert simple_job.schedule_type == ScheduleType.INTERVAL
        assert simple_job.interval == 60.0
        assert simple_job.priority == 1
        assert simple_job.status == JobStatus.PENDING
    
    def test_job_is_active(self, simple_job):
        assert simple_job.is_active is True
        simple_job.status = JobStatus.RUNNING
        assert simple_job.is_active is True
        simple_job.status = JobStatus.COMPLETED
        assert simple_job.is_active is False
    
    def test_job_is_completed(self, simple_job):
        assert simple_job.is_completed is False
        simple_job.status = JobStatus.COMPLETED
        assert simple_job.is_completed is True
        simple_job.status = JobStatus.FAILED
        assert simple_job.is_completed is True
    
    def test_job_should_retry(self, simple_job):
        simple_job.status = JobStatus.FAILED
        simple_job.retry_count = 0
        simple_job.max_retries = 3
        assert simple_job.should_retry is True
        
        simple_job.retry_count = 3
        assert simple_job.should_retry is False
    
    def test_job_get_next_run_time_interval(self, simple_job):
        simple_job.last_run = datetime.utcnow()
        next_run = simple_job.get_next_run_time()
        assert next_run is not None
        # Should be approximately 60 seconds from last run
        time_diff = (next_run - simple_job.last_run).total_seconds()
        assert abs(time_diff - 60.0) < 1.0
    
    def test_job_to_dict(self, simple_job):
        job_dict = simple_job.to_dict()
        assert job_dict["name"] == "test_job"
        assert job_dict["job_type"] == "periodic"
        assert job_dict["status"] == "pending"
    
    def test_job_from_dict(self, simple_job):
        job_dict = simple_job.to_dict()
        new_job = Job.from_dict(job_dict, simple_job.callback)
        assert new_job.name == simple_job.name
        assert new_job.job_type == simple_job.job_type


class TestSchedule:
    def test_schedule_creation(self):
        schedule = Schedule(
            schedule_id="",
            name="test_schedule",
            description="Test schedule",
            schedule_type=ScheduleType.INTERVAL,
            interval=300.0
        )
        assert schedule.schedule_id != ""
        assert schedule.name == "test_schedule"
        assert schedule.schedule_type == ScheduleType.INTERVAL
    
    def test_schedule_to_dict(self):
        schedule = Schedule(
            schedule_id="test_id",
            name="test_schedule",
            schedule_type=ScheduleType.INTERVAL,
            interval=300.0
        )
        schedule_dict = schedule.to_dict()
        assert schedule_dict["schedule_id"] == "test_id"
        assert schedule_dict["name"] == "test_schedule"
        assert schedule_dict["schedule_type"] == "interval"


class TestScheduler:
    def test_initialization(self, scheduler):
        assert scheduler is not None
        assert scheduler.max_workers == 2
        assert scheduler.max_queue_size == 100
        assert not scheduler.is_running
        assert len(scheduler.jobs) == 0
    
    @pytest.mark.asyncio
    async def test_add_job(self, scheduler, simple_job):
        job_id = await scheduler.add_job(simple_job)
        assert job_id == simple_job.job_id
        assert job_id in scheduler.jobs
        assert scheduler.jobs[job_id].name == "test_job"
    
    @pytest.mark.asyncio
    async def test_add_duplicate_job(self, scheduler, simple_job):
        job_id = await scheduler.add_job(simple_job)
        # Adding again should update
        simple_job.name = "updated_job"
        new_job_id = await scheduler.add_job(simple_job)
        assert new_job_id == job_id
        assert scheduler.jobs[job_id].name == "updated_job"
    
    @pytest.mark.asyncio
    async def test_remove_job(self, scheduler, simple_job):
        job_id = await scheduler.add_job(simple_job)
        result = await scheduler.remove_job(job_id)
        assert result is True
        assert job_id not in scheduler.jobs
    
    @pytest.mark.asyncio
    async def test_remove_nonexistent_job(self, scheduler):
        result = await scheduler.remove_job("nonexistent")
        assert result is False
    
    def test_get_job(self, scheduler, simple_job):
        # Need to add job first (sync version for testing)
        scheduler.jobs[simple_job.job_id] = simple_job
        retrieved = scheduler.get_job(simple_job.job_id)
        assert retrieved is not None
        assert retrieved.name == "test_job"
    
    def test_get_nonexistent_job(self, scheduler):
        retrieved = scheduler.get_job("nonexistent")
        assert retrieved is None
    
    def test_get_jobs_by_status(self, scheduler, simple_job):
        scheduler.jobs[simple_job.job_id] = simple_job
        pending_jobs = scheduler.get_jobs_by_status(JobStatus.PENDING)
        assert len(pending_jobs) == 1
        
        completed_jobs = scheduler.get_jobs_by_status(JobStatus.COMPLETED)
        assert len(completed_jobs) == 0
    
    def test_get_jobs_by_type(self, scheduler, simple_job):
        scheduler.jobs[simple_job.job_id] = simple_job
        periodic_jobs = scheduler.get_jobs_by_type(JobType.PERIODIC)
        assert len(periodic_jobs) == 1
        
        event_jobs = scheduler.get_jobs_by_type(JobType.EVENT_DRIVEN)
        assert len(event_jobs) == 0
    
    def test_get_jobs_by_tag(self, scheduler, simple_job):
        simple_job.tags = ["test", "important"]
        scheduler.jobs[simple_job.job_id] = simple_job
        
        test_jobs = scheduler.get_jobs_by_tag("test")
        assert len(test_jobs) == 1
        
        nonexistent_jobs = scheduler.get_jobs_by_tag("nonexistent")
        assert len(nonexistent_jobs) == 0
    
    def test_get_all_jobs(self, scheduler, simple_job):
        scheduler.jobs[simple_job.job_id] = simple_job
        all_jobs = scheduler.get_all_jobs()
        assert len(all_jobs) == 1
    
    def test_get_job_count(self, scheduler, simple_job):
        assert scheduler.get_job_count() == 0
        scheduler.jobs[simple_job.job_id] = simple_job
        assert scheduler.get_job_count() == 1
    
    def test_get_active_job_count(self, scheduler, simple_job):
        assert scheduler.get_active_job_count() == 0
        scheduler.jobs[simple_job.job_id] = simple_job
        assert scheduler.get_active_job_count() == 1
    
    @pytest.mark.asyncio
    async def test_add_schedule(self, scheduler):
        schedule = Schedule(
            schedule_id="",
            name="test_schedule",
            schedule_type=ScheduleType.INTERVAL,
            interval=300.0
        )
        schedule_id = await scheduler.add_schedule(schedule)
        assert schedule_id == schedule.schedule_id
        assert schedule_id in scheduler.schedules
    
    @pytest.mark.asyncio
    async def test_remove_schedule(self, scheduler):
        schedule = Schedule(
            schedule_id="test_schedule",
            name="test_schedule",
            schedule_type=ScheduleType.INTERVAL,
            interval=300.0
        )
        await scheduler.add_schedule(schedule)
        result = await scheduler.remove_schedule("test_schedule")
        assert result is True
        assert "test_schedule" not in scheduler.schedules
    
    def test_get_schedule(self, scheduler):
        schedule = Schedule(
            schedule_id="test_schedule",
            name="test_schedule",
            schedule_type=ScheduleType.INTERVAL,
            interval=300.0
        )
        scheduler.schedules["test_schedule"] = schedule
        retrieved = scheduler.get_schedule("test_schedule")
        assert retrieved is not None
        assert retrieved.name == "test_schedule"
    
    def test_get_all_schedules(self, scheduler):
        schedule = Schedule(
            schedule_id="test_schedule",
            name="test_schedule",
            schedule_type=ScheduleType.INTERVAL,
            interval=300.0
        )
        scheduler.schedules["test_schedule"] = schedule
        all_schedules = scheduler.get_all_schedules()
        assert len(all_schedules) == 1


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler):
        await scheduler.start()
        assert scheduler.is_running
        
        await scheduler.stop()
        assert not scheduler.is_running
    
    @pytest.mark.asyncio
    async def test_pause_resume(self, scheduler):
        await scheduler.start()
        assert not scheduler.is_paused
        
        await scheduler.pause()
        assert scheduler.is_paused
        
        await scheduler.resume()
        assert not scheduler.is_paused
        
        await scheduler.stop()
    
    @pytest.mark.asyncio
    async def test_get_status(self, scheduler):
        await scheduler.start()
        status = scheduler.get_status()
        assert status["running"] is True
        assert status["paused"] is False
        assert "jobs" in status
        assert "schedules" in status
        
        await scheduler.stop()
    
    @pytest.mark.asyncio
    async def test_get_summary(self, scheduler):
        await scheduler.start()
        summary = scheduler.get_summary()
        assert "total_jobs" in summary
        assert "active_jobs" in summary
        assert "completed_jobs" in summary
        
        await scheduler.stop()


class TestSchedulerEventHandling:
    @pytest.mark.asyncio
    async def test_trigger_event(self, scheduler):
        event_called = []
        
        def event_handler(event):
            event_called.append(event)
        
        scheduler.on_event("test_event", event_handler)
        await scheduler.start()
        
        await scheduler.trigger_event("test_event", {"data": "test"})
        
        # Give time for event to be processed
        await asyncio.sleep(0.2)
        
        await scheduler.stop()
        
        assert len(event_called) == 1
        assert event_called[0]["type"] == "test_event"
    
    @pytest.mark.asyncio
    async def test_event_driven_job(self, scheduler):
        job_called = []
        
        def job_callback():
            job_called.append(True)
        
        job = Job(
            job_id="",
            name="event_job",
            job_type=JobType.EVENT_DRIVEN,
            callback=job_callback,
            schedule_type=ScheduleType.INTERVAL,
            interval=60.0,
            metadata={"event_types": ["test_event"]}
        )
        
        await scheduler.add_job(job)
        await scheduler.start()
        
        await scheduler.trigger_event("test_event", {})
        
        # Give time for job to be processed
        await asyncio.sleep(0.3)
        
        await scheduler.stop()
        
        # Job should have been triggered
        assert len(job_called) >= 1


class TestSchedulerJobExecution:
    @pytest.mark.asyncio
    async def test_run_now(self, scheduler, simple_job):
        # Use ONE_TIME job type so it doesn't get rescheduled
        simple_job.job_type = JobType.ONE_TIME
        job_id = await scheduler.add_job(simple_job)
        await scheduler.start()
        
        result = await scheduler.run_now(job_id)
        assert result is True
        
        # Give time for job to run
        await asyncio.sleep(0.2)
        
        await scheduler.stop()
        
        # Check job status
        job = scheduler.get_job(job_id)
        assert job is not None
        assert job.status in [JobStatus.COMPLETED, JobStatus.FAILED]
    
    @pytest.mark.asyncio
    async def test_run_now_nonexistent(self, scheduler):
        result = await scheduler.run_now("nonexistent")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_execute_sync_job(self, scheduler, simple_job):
        # Use ONE_TIME job type so it doesn't get rescheduled
        simple_job.job_type = JobType.ONE_TIME
        job_id = await scheduler.add_job(simple_job)
        await scheduler.start()
        
        # Run job immediately
        await scheduler.run_now(job_id)
        await asyncio.sleep(0.2)
        
        await scheduler.stop()
        
        job = scheduler.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.result == "job completed"
    
    @pytest.mark.asyncio
    async def test_execute_async_job(self, scheduler, async_job):
        # Use ONE_TIME job type so it doesn't get rescheduled
        async_job.job_type = JobType.ONE_TIME
        job_id = await scheduler.add_job(async_job)
        await scheduler.start()
        
        # Run job immediately
        await scheduler.run_now(job_id)
        await asyncio.sleep(0.3)
        
        await scheduler.stop()
        
        job = scheduler.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.result == "async job completed"
    
    @pytest.mark.asyncio
    async def test_job_timeout(self, scheduler):
        async def slow_callback():
            await asyncio.sleep(10)  # Longer than timeout
            return "completed"
        
        job = Job(
            job_id="",
            name="slow_job",
            job_type=JobType.ONE_TIME,
            callback=slow_callback,
            timeout=0.1  # Very short timeout
        )
        
        job_id = await scheduler.add_job(job)
        await scheduler.start()
        
        await scheduler.run_now(job_id)
        await asyncio.sleep(0.3)
        
        await scheduler.stop()
        
        job = scheduler.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert "timeout" in job.error.lower()
    
    @pytest.mark.asyncio
    async def test_job_retry(self, scheduler):
        call_count = [0]
        
        def failing_callback():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Temporary failure")
            return "success"
        
        job = Job(
            job_id="",
            name="retry_job",
            job_type=JobType.ONE_TIME,
            callback=failing_callback,
            max_retries=3,
            retry_delay=0.01
        )
        
        job_id = await scheduler.add_job(job)
        await scheduler.start()
        
        await scheduler.run_now(job_id)
        # Wait longer for retries to happen
        await asyncio.sleep(1.0)
        
        await scheduler.stop()
        
        job = scheduler.get_job(job_id)
        assert job is not None
        # Should eventually succeed after retries
        assert job.status == JobStatus.COMPLETED
        assert job.retry_count == 2
        assert call_count[0] == 3
