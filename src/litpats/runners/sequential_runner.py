class SimpleRunner(object):
    """Runs tests one at a time, in the current process"""

    def __init__(self):
        self._results = []
        self._tasks = []

    def add_task(self, func, *args, **kwargs):
        self._tasks.append((func, args, kwargs))

    def run_tasks(self):
        for (func, args, kwargs) in self._tasks:
            self._results.append(func(*args, **kwargs))
        return self._results
