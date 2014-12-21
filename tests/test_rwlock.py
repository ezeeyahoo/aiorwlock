import asyncio
from functools import wraps

import unittest
from unittest import mock

from aiorwlock import RWLock


def run_until_complete(fun):
    if not asyncio.iscoroutinefunction(fun):
        fun = asyncio.coroutine(fun)

    @wraps(fun)
    def wrapper(test, *args, **kw):
        loop = test.loop
        ret = loop.run_until_complete(
            asyncio.wait_for(fun(test, *args, **kw), 15, loop=loop))
        return ret
    return wrapper


class Bunch(object):
    """A bunch of Tasks.
    """
    def __init__(self, f, n, wait_before_exit=False, loop=None):
        """
        Construct a bunch of `n` threads running the same function `f`.
        If `wait_before_exit` is True, the threads won't terminate until
        do_finish() is called.
        """
        self._loop = loop or asyncio.get_event_loop()
        self.f = f
        self.n = n
        self.started = []
        self.finished = []
        self._can_exit = not wait_before_exit

        self._futures = []

        @asyncio.coroutine
        def task():
            tid = asyncio.Task.current_task(loop=self._loop)
            self.started.append(tid)
            try:
                yield from f()
            finally:
                self.finished.append(tid)
                while not self._can_exit:
                    yield from asyncio.sleep(0.01, loop=self._loop)

        for i in range(n):
            t = asyncio.Task(task(), loop=self._loop)
            self._futures.append(t)

    @asyncio.coroutine
    def wait_for_finished(self):
        yield from asyncio.gather(*self._futures, loop=self._loop)

    def do_finish(self):
        self._can_exit = True


def _wait(loop=None):
    _loop = loop or asyncio.get_event_loop()
    yield from asyncio.sleep(0.01, loop=_loop)


class TestRWLockReader(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        self.loop.close()
        del self.loop

    def get_reader_lock(self, loop=None):
        return RWLock(loop=loop).reader_lock

    def get_writer_lock(self, loop=None):
        return RWLock(loop=loop).writer_lock

    def test_ctor_loop(self):
        loop = mock.Mock()
        rwlock = self.get_reader_lock(loop=loop)
        self.assertIs(rwlock.lock._loop, loop)

        rwlock = RWLock(loop=self.loop).reader_lock
        self.assertIs(rwlock.lock._loop, self.loop)

    def test_ctor_noloop(self):
        asyncio.set_event_loop(self.loop)
        rwlock = self.get_reader_lock(loop=None)
        self.assertIs(rwlock.lock._loop, self.loop)

    @run_until_complete
    def test_repr(self):
        rwlock = RWLock(loop=self.loop)
        self.assertTrue('RWLock' in rwlock.__repr__())
        self.assertTrue('WriterLock: [unlocked' in rwlock.__repr__())
        self.assertTrue('ReaderLock: [unlocked' in rwlock.__repr__())

        # reader lock __repr__
        yield from rwlock.reader_lock.acquire()
        self.assertTrue('ReaderLock: [locked]' in rwlock.__repr__())
        yield from rwlock.reader_lock.release()
        self.assertTrue('ReaderLock: [unlocked]' in rwlock.__repr__())

        # writer lock __repr__
        yield from rwlock.writer_lock.acquire()
        self.assertTrue('WriterLock: [locked]' in rwlock.__repr__())
        yield from rwlock.writer_lock.release()
        self.assertTrue('WriterLock: [unlocked]' in rwlock.__repr__())

    @run_until_complete
    def test_many_readers(self):
        rwlock = RWLock(loop=self.loop)
        N = 5
        locked = []
        nlocked = []

        @asyncio.coroutine
        def f():
            try:
                yield from rwlock.reader_lock.acquire()
                locked.append(1)
                yield from _wait(loop=self.loop)
                nlocked.append(len(locked))
                yield from _wait(loop=self.loop)
                locked.pop(-1)
            finally:
                yield from rwlock.writer_lock.release()

        yield from Bunch(f, N, loop=self.loop).wait_for_finished()
        self.assertTrue(max(nlocked) > 1)

    @run_until_complete
    def test_reader_recursion(self):

        rwlock = RWLock(loop=self.loop)
        N = 5
        locked = []
        nlocked = []

        @asyncio.coroutine
        def f():
            try:
                yield from rwlock.reader_lock.acquire()
                try:
                    yield from rwlock.reader_lock.acquire()
                    locked.append(1)
                    yield from _wait(loop=self.loop)
                    nlocked.append(len(locked))
                    yield from _wait(loop=self.loop)
                    locked.pop(-1)
                finally:
                    yield from rwlock.reader_lock.release()
            finally:
                yield from rwlock.reader_lock.release()

        yield from Bunch(f, N, loop=self.loop).wait_for_finished()
        self.assertTrue(max(nlocked) > 1)

    @run_until_complete
    def test_writer_recursion(self):
        rwlock = RWLock(loop=self.loop)
        N = 5
        locked = []
        nlocked = []

        @asyncio.coroutine
        def f():
            try:
                yield from rwlock.writer_lock.acquire()
                try:
                    yield from rwlock.writer_lock.acquire()
                    locked.append(1)
                    yield from _wait(loop=self.loop)
                    nlocked.append(len(locked))
                    yield from _wait(loop=self.loop)
                    locked.pop(-1)
                finally:
                    yield from rwlock.reader_lock.release()
            finally:
                yield from rwlock.reader_lock.release()

        yield from Bunch(f, N, loop=self.loop).wait_for_finished()
        self.assertEqual(max(nlocked), 1)

    @run_until_complete
    def test_writer_then_reader_recursion(self):
        rwlock = RWLock(loop=self.loop)
        N = 5
        locked = []
        nlocked = []

        @asyncio.coroutine
        def f():
            try:
                yield from rwlock.writer_lock.acquire()
                try:
                    yield from rwlock.reader_lock.acquire()
                    locked.append(1)
                    yield from _wait(loop=self.loop)
                    nlocked.append(len(locked))
                    yield from _wait(loop=self.loop)
                    locked.pop(-1)
                finally:
                    yield from rwlock.reader_lock.release()
            finally:
                yield from rwlock.writer_lock.release()

        yield from Bunch(f, N, loop=self.loop).wait_for_finished()
        self.assertEqual(max(nlocked), 1)

    @run_until_complete
    def test_writer_recursionfail(self):
        rwlock = RWLock(loop=self.loop)
        N = 5
        locked = []

        @asyncio.coroutine
        def f():
            try:
                yield from rwlock.reader_lock.acquire()
                with self.assertRaises(RuntimeError):
                    yield from rwlock.writer_lock.acquire()
                locked.append(1)
            finally:
                yield from rwlock.reader_lock.release()

        yield from Bunch(f, N, loop=self.loop).wait_for_finished()
        self.assertEqual(len(locked), N)

    @run_until_complete
    def test_readers_writers(self):
        rwlock = RWLock(loop=self.loop)
        N = 5
        rlocked = []
        wlocked = []
        nlocked = []

        @asyncio.coroutine
        def r():
            try:
                yield from rwlock.reader_lock.acquire()
                rlocked.append(1)
                yield from _wait(loop=self.loop)
                nlocked.append((len(rlocked), len(wlocked)))
                yield from _wait(loop=self.loop)
                rlocked.pop(-1)
            finally:
                yield from rwlock.reader_lock.release()

        @asyncio.coroutine
        def w():
            try:
                yield from rwlock.writer_lock.acquire()
                wlocked.append(1)
                yield from _wait(loop=self.loop)
                nlocked.append((len(rlocked), len(wlocked)))
                yield from _wait(loop=self.loop)
                wlocked.pop(-1)
            finally:
                yield from rwlock.writer_lock.release()

        b1 = Bunch(r, N, loop=self.loop)
        b2 = Bunch(w, N, loop=self.loop)

        yield from asyncio.sleep(0.0001, loop=self.loop)

        yield from b1.wait_for_finished()
        yield from b2.wait_for_finished()

        r, w, = zip(*nlocked)

        self.assertTrue(max(r) > 1)
        self.assertEqual(max(w), 1)

        for r, w in nlocked:
            if w:
                self.assertEqual(r, 0)
            if r:
                self.assertEqual(w, 0)

    @run_until_complete
    def test_writer_success(self):
        """Verify that a writer can get access"""
        rwlock = RWLock(loop=self.loop)
        N = 5
        reads = 0
        writes = 0

        @asyncio.coroutine
        def r():
            # read until we achive write successes
            nonlocal reads, writes
            while writes < 2:
                try:
                    yield from rwlock.reader_lock.acquire()
                    # TODO: fix this, why there is no switch here?
                    yield from asyncio.sleep(0.0, loop=self.loop)
                    reads += 1
                    # print("current reads", reads)
                finally:
                    yield from rwlock.reader_lock.release()

        @asyncio.coroutine
        def w():
            nonlocal reads, writes
            while reads == 0:
                yield from _wait(loop=self.loop)

            for i in range(2):
                yield from _wait(loop=self.loop)

                try:
                    yield from rwlock.writer_lock.acquire()
                    writes += 1
                    # print("current writes", reads)

                finally:
                    yield from rwlock.writer_lock.release()

        b1 = Bunch(r, N, loop=self.loop)
        # yield from asyncio.sleep(0.0, loop=self.loop)

        b2 = Bunch(w, 1, loop=self.loop)
        # yield from asyncio.sleep(0.0001, loop=self.loop)

        yield from b1.wait_for_finished()
        yield from b2.wait_for_finished()
        self.assertEqual(writes, 2)
        # uncomment this to view performance
        # print('>>>>>>>>>>>', writes, reads)