# Persistent operation journal

The Local rescue UI records capture, restore and direct local clone operations
in /home/feclora/logs/operations.jsonl.

The journal is append-only JSON Lines. Each operation emits a started event
and then one terminal event: completed, failed or cancelled. Events share a UUID
and include the operation name, target device, optional image identifier, UTC
timestamp and (for failures) exception type and a bounded error message.

The directory is created with mode 0700; the journal file is created and
maintained with mode 0600. Writes use O_APPEND, reject a symlink at the journal
path, take an advisory exclusive lock, and call fsync after each event. The UI
refuses to start a logged operation if the initial event cannot be persisted.

A power loss can leave a started event without a terminal event. Such an entry
means the operation outcome is unknown and the target must be inspected; the
journal does not claim automatic rollback or crash recovery. Rotation,
tamper-evident chaining, log export and a UI history browser remain future work.
