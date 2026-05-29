# test_treasury.py

import unittest
from unittest.mock import patch, MagicMock
from treasury_manager import TreasuryManager

# Fake logger to prevent writing fake logs
class DummyLogger:
    def info(self, strat, msg): pass
    def error(self, strat, msg): pass
    def success(self, strat, msg): pass
    def _get_connection(self): return MagicMock()
    
class TestTreasuryManager(unittest.TestCase):
    @patch('treasury_manager.TreasuryManager._save_state_to_db')
    def test_sol_breakout_math(self, mock_save):
        # 1. Setup: Give it exactly $10,000 to manage
        treasury = TreasuryManager(DummyLogger(), initial_capital=10000.00, environment="TEST")
        
        # 2. Action: Shift to the SOL playbook
        success = treasury.execute_playbook("sol_breakout")
        
        # 3. Assertions: Verify the engine did exactly what we expect
        self.assertTrue(success, "Playbook should execute successfully")
        
        # 4. Verify: 60% SOL allocation math
        self.assertEqual(treasury.allocations["sol_pure"], 6000.00, "SOL should receive exactly 60%")
        self.assertEqual(treasury.allocations["eth_pure"], 1500.00, "ETH should receive exactly 15%")
        
        # 5. Verify: Reserve calculation
        expected_allocated = 6000.0 + 1500.0 + 1500.0 + 500.0
        expected_reserve = 10000.00 - expected_allocated
        self.assertEqual(treasury.reserve, expected_reserve, "Reserve math is incorrect")
        
        # 6. Verify: Attempted to save to db (blocked actually)
        mock_save.assert_called_with("sol_breakout")
        
if __name__ == '__main__':
    unittest.main()