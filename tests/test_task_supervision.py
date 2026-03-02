from __future__ import annotations

import asyncio
import unittest

from app.task_supervision import TaskSupervisor


class TaskSupervisionTests(unittest.TestCase):
    def test_spawn_tracks_task(self) -> None:
        async def run() -> None:
            sup = TaskSupervisor()

            async def worker() -> int:
                await asyncio.sleep(0.001)
                return 1

            task = sup.spawn(worker())
            self.assertIn(task, sup.background_tasks)
            await task
            await asyncio.sleep(0)
            self.assertNotIn(task, sup.background_tasks)

        asyncio.run(run())

    def test_shutdown_cancels_tasks(self) -> None:
        async def run() -> None:
            sup = TaskSupervisor()

            async def sleeper() -> None:
                await asyncio.sleep(10)

            bg = sup.spawn(sleeper())
            startup = asyncio.create_task(sleeper())
            await sup.shutdown(startup_task=startup, timeout=0.01)
            self.assertTrue(bg.cancelled() or bg.done())
            self.assertTrue(startup.cancelled() or startup.done())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
