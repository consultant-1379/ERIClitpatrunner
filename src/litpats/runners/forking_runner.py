import cStringIO
import errno
import fcntl
import os
import select
import sys


class BufferedStream(object):
    '''
    Wrapper class for use with select.select(), to buffer data.
    '''

    def __init__(self, fd):
        self._fd = fd
        # make descriptor non-blocking
        fl = fcntl.fcntl(self._fd, fcntl.F_GETFL)
        fcntl.fcntl(self._fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        # allocate a buffer
        self._buf = cStringIO.StringIO()

    def fileno(self):
        """Returns file descriptor: needed for select()"""
        return self._fd

    def handle_data(self):
        '''
        Drain data from the file descriptor and append it to the
        buffer.
        '''

        try:
            data = os.read(self._fd, 1024)
            while len(data):
                self._buf.write(data)
                data = os.read(self._fd, 1024)
        except OSError as ex:
            if ex.errno != errno.EAGAIN:
                raise ex

    def get_data(self):
        """Retrieve buffered data"""
        data = self._buf.getvalue()
        self._buf.close()
        return data

    def close(self):
        """Close descriptor"""
        os.close(self._fd)


class Task(object):

    WAITING = 1
    RUNNING = 2
    DONE = 3

    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.worker_pid = None
        # These attributes are only to be used by the parent process!
        self.state = self.WAITING
        self.out_stream = None
        self.err_stream = None

    def start(self):
        sys.stdout.flush()
        sys.stderr.flush()

        stdout_pipe_r, stdout_pipe_w = os.pipe()
        stderr_pipe_r, stderr_pipe_w = os.pipe()

        pid = os.fork()

        if pid == 0:
            #child
            os.close(stdout_pipe_r)
            os.close(stderr_pipe_r)
            os.dup2(stdout_pipe_w, sys.stdout.fileno())
            os.dup2(stderr_pipe_w, sys.stderr.fileno())

            # XXX Do we need to synchronise with the parent before we
            # proceed?
            func_result = self.func(*self.args, **self.kwargs)
            #print "func_result: %s" % (str(func_result))
            sys.stdout.flush()
            sys.stderr.flush()
            if func_result:
                os._exit(0)
            else:
                os._exit(1)
        else:
            #parent
            self.worker_pid = pid

            os.close(stdout_pipe_w)
            os.close(stderr_pipe_w)
            self.out_stream = BufferedStream(stdout_pipe_r)
            self.err_stream = BufferedStream(stderr_pipe_r)
            self.state = self.RUNNING
            # XXX Do we need to synchronise with the child before we allow
            # it to proceed?

        return True

    def close_worker_buffered_streams(self):
        '''
        Drain and close the BufferedStream objects used for the worker's
        stdout and stderr pipes.
        '''
        self.out_stream.handle_data()
        self.out_stream.close()
        self.err_stream.handle_data()
        self.err_stream.close()

    def dump_output(self):
        if self.state != self.DONE:
            raise Exception("Unexpected state {0}".format(self.state))
        sys.stdout.write(self.out_stream.get_data())
        sys.stdout.flush()
        sys.stderr.write(self.err_stream.get_data())
        sys.stderr.flush()


class ForkingRunner(object):
    '''
    Runs multiple tests at a time, in child processes
    '''

    def __init__(self, num_workers=4):
        self._num_workers = num_workers
        self._tasks = []

    def add_task(self, func, *args, **kwargs):
        self._tasks.append(Task(func, *args, **kwargs))

    def _reap_child(self, pid, status):
        #print "pid: %d status: %d" % (pid, status)
        found = False
        for t in self._tasks:
            if t.state == t.RUNNING and t.worker_pid == pid:
                found = True
                t.close_worker_buffered_streams()
                t.result = (status == 0)
                t.state = t.DONE
                t.worker_pid = None
                break
        if not found:
            raise Exception('Unexpected child pid: %d' % pid)

    def run_tasks(self):
        results = []
        SELECT_TIMEOUT = 10.0
        while self._tasks:
            running = [t for t in self._tasks if t.state == t.RUNNING]
            waiting = [t for t in self._tasks if t.state == t.WAITING]

            # Spawn new workers, up to specified number
            while (len(running) < self._num_workers) and waiting:
                waiting[0].start()
                running = [t for t in self._tasks if t.state == t.RUNNING]
                waiting = [t for t in self._tasks if t.state == t.WAITING]

            if running:
                # Read and buffer available data from child stdout/stderr

                read_streams = [t.out_stream for t in running]
                read_streams.extend([t.err_stream for t in running])

                read_streams, _, _ = select.select(read_streams,
                                             [], [], SELECT_TIMEOUT)
                for s in read_streams:
                    s.handle_data()

            # Reap any dead children
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                while pid != 0:
                    self._reap_child(pid, status)
                    pid, status = os.waitpid(-1, os.WNOHANG)
            except OSError as ex:
                if ex.errno != errno.ECHILD:
                    raise ex

            # Output the results from any completed tasks at head of list,
            # and remove them
            while self._tasks and self._tasks[0].state == Task.DONE:
                t = self._tasks.pop(0)
                results.append(t.result)
                t.dump_output()

        return results
