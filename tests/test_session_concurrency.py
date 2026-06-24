import threading
from unittest.mock import patch, MagicMock
import src.crawler
import src.auto_discover_trials


def test_crawler_session_concurrency():
    """Verify that crawler.get_session() is thread-safe and creates only one session."""
    src.crawler.reset_session()

    with patch("requests.Session") as mock_session_cls:
        mock_session_cls.side_effect = lambda: MagicMock()

        num_threads = 20
        sessions = [None] * num_threads

        def get_and_store_session(index):
            sessions[index] = src.crawler.get_session()

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=get_and_store_session, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify that all threads got the same session object
        first_session = sessions[0]
        assert first_session is not None
        for s in sessions:
            assert s is first_session

        # Verify that requests.Session was only called once
        assert mock_session_cls.call_count == 1


def test_auto_discover_session_concurrency():
    """Verify that auto_discover_trials.get_session() is thread-safe."""
    # Since there is no reset_session in auto_discover_trials, we manually reset
    with src.auto_discover_trials._session_lock:
        src.auto_discover_trials._session = None

    with patch("requests.Session") as mock_session_cls:
        mock_session_cls.side_effect = lambda: MagicMock()

        num_threads = 20
        sessions = [None] * num_threads

        def get_and_store_session(index):
            sessions[index] = src.auto_discover_trials.get_session()

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=get_and_store_session, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify that all threads got the same session object
        first_session = sessions[0]
        assert first_session is not None
        for s in sessions:
            assert s is first_session

        # Verify that requests.Session was only called once
        assert mock_session_cls.call_count == 1
