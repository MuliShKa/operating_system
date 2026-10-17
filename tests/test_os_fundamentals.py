import unittest
import time
import multiprocessing

def worker_no_lock(shared_counter, iterations):
    """
    Increments a shared counter without a lock.
    Forces a context switch using time.sleep() to create a race condition.
    """
    for _ in range(iterations):
        temp = shared_counter.value
        time.sleep(0.001)
        shared_counter.value = temp + 1

def worker_with_lock(shared_counter, lock, iterations):
    """
    Increments a shared counter safely using a Mutex (lock).
    """
    for _ in range(iterations):
        lock.acquire()
        try:
            temp = shared_counter.value
            time.sleep(0.001)
            shared_counter.value = temp + 1
        finally:
            lock.release()
            
def deadlock_worker(lock_1, lock_2, success_flag, barrier):
    """
    Attempts to acquire two locks. Uses a timeout to prevent a permanent hang (Deadlock).
    Scenario OS5-3. Uses a barrier and a hold-delay to ensure a perfect collision.
    """
    if lock_1.acquire(timeout=2.0):
        # This guarantees a 100% perfect deadlock condition.
        barrier.wait()
        
        if lock_2.acquire(timeout=0.2):
            success_flag.value = 1 
            lock_2.release()
        else:
            success_flag.value = 0
            
        # This ensures the other process also times out.
        time.sleep(0.5)
        lock_1.release()

class TestOSFundamentalsOS5(unittest.TestCase):
    """
    Operating System fundamentals test suite for the OS5 node.
    Verifies concurrency, database (WAL) behavior, and failure scenarios.
    """

    def setUp(self):
        # Setup environment before each test (e.g., clean DB)
        pass

    def tearDown(self):
        # Clean up resources after each test
        pass
        

    # =========================================================================
    # Test 1: Race condition & Deadlock tests
    # =========================================================================
    
    def test_race_condition_without_lock(self):
        """
        Verifies that a shared counter loses values when modified concurrently
        without a lock (mutex).
        """
        iterations = 40
        counter = multiprocessing.Value('i', 0)
        
        p1 = multiprocessing.Process(target=worker_no_lock, args=(counter, iterations))
        p2 = multiprocessing.Process(target=worker_no_lock, args=(counter, iterations))
        
        p1.start()
        p2.start()
        p1.join()
        p2.join()
        
        self.assertLess(counter.value, iterations * 2, "Counter should lose values without a lock.")

    def test_race_condition_with_lock(self):
        """
        Verifies that the counter result is exact when using a lock (mutex).
        """
        iterations = 40
        counter = multiprocessing.Value('i', 0)
        lock = multiprocessing.Lock()
        
        p1 = multiprocessing.Process(target=worker_with_lock, args=(counter, lock, iterations))
        p2 = multiprocessing.Process(target=worker_with_lock, args=(counter, lock, iterations))
        
        p1.start()
        p2.start()
        p1.join()
        p2.join()
        
        self.assertEqual(counter.value, iterations * 2, "Counter must be exact when using a lock.")

    def test_deadlock_recovery_with_timeout(self):
        """
        Scenario OS5-3: Demonstrates that 'acquire(timeout=0.2)' prevents a permanent deadlock.
        """
        lock_a = multiprocessing.Lock()
        lock_b = multiprocessing.Lock()
        flag_p1 = multiprocessing.Value('i', -1)
        flag_p2 = multiprocessing.Value('i', -1)
        
        barrier = multiprocessing.Barrier(2)

        p1 = multiprocessing.Process(target=deadlock_worker, args=(lock_a, lock_b, flag_p1, barrier))
        p2 = multiprocessing.Process(target=deadlock_worker, args=(lock_b, lock_a, flag_p2, barrier))

        p1.start()
        p2.start()
        p1.join()
        p2.join()

        self.assertEqual(flag_p1.value, 0, "Process 1 should have recovered using the 0.2s timeout.")
        self.assertEqual(flag_p2.value, 0, "Process 2 should have recovered using the 0.2s timeout.")

    # =========================================================================
    # Test 2: Database WAL mode & Atomic writes
    # =========================================================================

    def test_database_wal_mode_and_atomic_writes(self):
        pass

    # =========================================================================
    # Test 3: Rules and Command TTL (Expiry)
    # =========================================================================

    def test_water_level_rule_below_threshold(self):
        pass

    def test_water_level_rule_above_threshold(self):
        pass

    def test_command_ttl_expiration(self):
        pass

    # =========================================================================
    # Test 4 and 5: Failures, Backup & Offline Demo validation
    # =========================================================================

    def test_process_restart_recovery(self):
        pass

    def test_backup_with_flock(self):
        pass

    def test_offline_demo_data_consistency(self):
        pass

if __name__ == '__main__':
    unittest.main()