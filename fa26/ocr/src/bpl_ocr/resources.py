"""Sample this worker and its descendants; report RSS sums, not unique RAM."""

import threading
import time

import psutil


class ProcessSampler:
    def __init__(self, interval=0.1):
        self.interval = interval
        self.root = psutil.Process()
        self.stop = threading.Event()
        self.peak = self.samples = self.errors = 0
        self.tree_failures = 0
        self.cpu = {}
        self.start_cpu = sum(self.root.cpu_times()[:2])
        self.started = time.perf_counter()

    def sample(self):
        rss = 0
        try:
            processes = [self.root, *self.root.children(recursive=True)]
        except (psutil.Error, OSError):
            self.errors += 1
            self.tree_failures += 1
            processes = [self.root]
        for process in processes:
            try:
                with process.oneshot():
                    key = (process.pid, process.create_time())
                    rss += process.memory_info().rss
                    self.cpu[key] = max(self.cpu.get(key, 0), sum(process.cpu_times()[:2]))
            except (psutil.Error, OSError):
                self.errors += 1
        self.peak = max(self.peak, rss)
        self.samples += 1

    def loop(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *unused):
        self.stop.set()
        self.thread.join()
        self.sample()

    def result(self):
        return {"sampler": "psutil " + psutil.__version__, "sample_interval_s": self.interval,
                "peak_process_tree_rss_bytes": self.peak, "samples": self.samples,
                "unavailable_process_samples": self.errors,
                "tree_enumeration_failures": self.tree_failures,
                "sampled_cpu_seconds_lower_bound": max(0, sum(self.cpu.values()) - self.start_cpu),
                "measurement_wall_s": time.perf_counter() - self.started,
                "definition": "Sampled sum of worker and descendant RSS, including shared pages more than once. CPU sums observed per-process user+system maxima; short-lived/unobserved final CPU is omitted. Neither is a whole-host measurement or an exact peak."}
