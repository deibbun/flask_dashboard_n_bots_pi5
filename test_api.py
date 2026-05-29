# test_api.py

import unittest
from unittest.mock import patch
from app import ExecutiveEngineApp

class TestDashboardAPI(unittest.TestCase):

    def setUp(self):
        # Initialize the app but swap out the real dependencies
        with patch('app.KrakenPrivateClient'), patch('app.BotLogger'):
            self.engine = ExecutiveEngineApp()
            # Set to paper mode for maximum safety during tests
            self.engine.LIVE_MODE = False 
            self.engine.db_log.environment = "TEST"
            
            # Create the test client
            self.client = self.engine.app.test_client()

    # Block the real database connection
    @patch('app.ExecutiveEngineApp.get_db_connection')
    def test_change_play_route(self, mock_db_conn):
        # Simulate the frontend sending JSON to the change_play endpoint
        payload = {"play_name": "defensive"}
        response = self.client.post('/api/change_play', json=payload)
        
        # Verify the server responded with a 200 OK
        self.assertEqual(response.status_code, 200)
        
        # Verify the JSON payload matches our expected success structure
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Strategy shifted to defensive")

    def test_change_play_empty_payload(self):
        # Simulate a broken frontend sending empty data
        response = self.client.post('/api/change_play', json={})
        data = response.get_json()
        
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "No play_name provided.")

if __name__ == '__main__':
    unittest.main()