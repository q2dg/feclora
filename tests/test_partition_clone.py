import io
import json
import unittest
from types import SimpleNamespace
from feclora.storage.partition_clone import PartitionCloneError, clone_partition

class Sink:
    def __init__(self): self.data = io.BytesIO()
    def write(self, data): return self.data.write(data)
    def close(self): pass
    def getvalue(self): return self.data.getvalue()

class Proc:
    def __init__(self, output=b""):
        self.stdout = io.BytesIO(output)
        self.stdin = Sink()
        self.rc = 0
    def wait(self, *args, **kwargs): return self.rc
    def poll(self): return self.rc
    def terminate(self): self.rc = -15
    def kill(self): self.rc = -9

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload = b"partition-data" * 80
        self.calls = []
        self.processes = []
    def runner(self, command, **kwargs):
        if "--inverse" in command:
            disk = "/dev/sda" if command[-1] == "/dev/sda1" else "/dev/sdb"
            value = {"blockdevices": [{"path": disk, "type": "disk"}]}
        else:
            size = len(self.payload) if command[-1] == "/dev/sda1" else len(self.payload) + 1024
            value = {"blockdevices": [{"size": str(size), "type": "part", "log-sec": "512", "ro": False}]}
        return SimpleNamespace(stdout=json.dumps(value))
    def factory(self, argv, **kwargs):
        n = len(self.calls)
        self.calls.append(argv)
        proc = Proc(self.payload if n in (0, 2) else b"")
        self.processes.append(proc)
        return proc
    def run_clone(self, **kwargs):
        return clone_partition(
            "/dev/sda1", "/dev/sdb1",
            confirmation="ERASE /dev/sdb1 FROM /dev/sda1",
            executables={"lsblk": "lsblk", "dd": "dd"},
            device_validator=lambda p: True, runner=self.runner,
            popen_factory=self.factory, device_safety_check=lambda p: None,
            effective_uid=lambda: 0, **kwargs)
    def test_copy_and_readback(self):
        progress = []
        self.assertEqual(self.run_clone(progress_callback=lambda a,b: progress.append((a,b))), len(self.payload))
        self.assertEqual(self.processes[1].stdin.getvalue(), self.payload)
        self.assertEqual(progress[-1], (len(self.payload) * 2, len(self.payload) * 2))
        self.assertEqual(len(self.calls), 3)
    def test_confirmation_gate(self):
        with self.assertRaises(PartitionCloneError):
            clone_partition("/dev/sda1", "/dev/sdb1", confirmation="no",
                executables={"lsblk":"lsblk","dd":"dd"}, device_validator=lambda p: True,
                runner=self.runner, popen_factory=self.factory,
                device_safety_check=lambda p: None, effective_uid=lambda: 0)
        self.assertEqual(self.calls, [])
    def test_same_backing_disk_rejected(self):
        def same(command, **kwargs):
            if "--inverse" in command:
                return SimpleNamespace(stdout=json.dumps({"blockdevices":[{"path":"/dev/sda","type":"disk"}]}))
            return self.runner(command, **kwargs)
        with self.assertRaisesRegex(PartitionCloneError, "share a physical backing disk"):
            clone_partition("/dev/sda1","/dev/sdb1",confirmation="ERASE /dev/sdb1 FROM /dev/sda1",
                executables={"lsblk":"lsblk","dd":"dd"},device_validator=lambda p: True,
                runner=same,popen_factory=self.factory,device_safety_check=lambda p: None,
                effective_uid=lambda: 0)
        self.assertEqual(self.calls, [])

if __name__ == "__main__": unittest.main()
