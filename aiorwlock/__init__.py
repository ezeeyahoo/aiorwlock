import asyncio

__version__ = '0.0.1'
__all__ = ['RWLock']


# The internal lock object managing the RWLock state.
class _RWLockCore:
    def __init__(self, loop=None):
        self._loop = loop or asyncio.get_event_loop()

        self._cond = asyncio.Condition(loop=self._loop)
        self._state = 0  # positive is shared count, negative exclusive count
        self._waiting = 0
        self._owning = []  # threads will be few, so a list is not inefficient

    # Acquire the lock in read mode.
    @asyncio.coroutine
    def acquire_read(self):
        with (yield from self._cond):
            return (yield from self._cond.wait_for(self._acquire_read))

    def _acquire_read(self):
        if self._state < 0:
            # lock is in write mode.  See if it is ours and we can recurse
            return self._acquire_write()

        # Implement "exclusive bias" giving exclusive lock priority.

        me = asyncio.Task.current_task(loop=self._loop)
        if not self._waiting:
            ok = True  # no exclusive acquires waiting.
        else:
            # Recursion must have the highest priority, otherwise we deadlock
            ok = me in self._owning

        if ok:
            self._state += 1
            self._owning.append(me)
        return ok

    # Acquire the lock in write mode.  A 'waiting' count is maintainded,
    # ensurring that 'readers' will yield to writers.
    @asyncio.coroutine
    def acquire_write(self):
        with (yield from self._cond):
            self._waiting += 1
            try:
                return (yield from self._cond.wait_for(self._acquire_write))
            finally:
                self._waiting -= 1

    def _acquire_write(self):
        # we can only take the write lock if no one is there,
        # or we already hold the lock
        me = asyncio.Task.current_task(loop=self._loop)
        if self._state == 0 or (self._state < 0 and me in self._owning):
            self._state -= 1
            self._owning.append(me)
            return True
        if self._state > 0 and me in self._owning:
            raise RuntimeError("cannot upgrade RWLock from read to write")
        return False

    # Release the lock
    @asyncio.coroutine
    def release(self):
        with (yield from self._cond):
            me = asyncio.Task.current_task(loop=self._loop)
            try:
                self._owning.remove(me)
            except ValueError:
                raise RuntimeError("cannot release an un-acquired lock")
            if self._state > 0:
                self._state -= 1
            else:
                self._state += 1
            if self._state == 0:
                self._cond.notify_all()


# Lock objects to access the _RWLockCore in reader or writer mode
class _ReaderLock:
    def __init__(self, lock):
        self.lock = lock
        self._locked = False

    @asyncio.coroutine
    def acquire(self):
        yield from self.lock.acquire_read()
        self._locked = True

    @asyncio.coroutine
    def release(self):
        yield from self.lock.release()
        self._locked = False

    def __repr__(self):
        status = 'locked' if self._locked else 'unlocked'
        return "<ReaderLock: [{}]>".format(status)


class _WriterLock(_ReaderLock):
    @asyncio.coroutine
    def acquire(self):
        yield from self.lock.acquire_write()
        self._locked = True

    def __repr__(self):
        status = 'locked' if self._locked else 'unlocked'
        return "<WriterLock: [{}]>".format(status)


class RWLock:
    # Doc shamelessly ripped off from Java
    """
    A RWLock maintains a pair of associated locks, one for read-only operations
    and one for writing. The read lock may be held simultaneously by multiple
    reader threads, so long as there are no writers. The write lock is
    exclusive.
    """
    core = _RWLockCore

    def __init__(self, loop=None):
        self._loop = loop or asyncio.get_event_loop()
        core = self.core(loop=self._loop)
        self._reader_lock = _ReaderLock(core)
        self._writer_lock = _WriterLock(core)

    @property
    def reader_lock(self):
        """
        The lock used for read, or shared, access
        """
        return self._reader_lock

    @property
    def writer_lock(self):
        """
        The lock used for write, or exclusive, access
        """
        return self._writer_lock

    def __repr__(self):
        r = '<RWLock: {} {}>'.format(self.reader_lock.__repr__(),
                                     self.writer_lock.__repr__())
        return r