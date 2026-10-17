import unittest

from src.tauri_shim import get_tauri_shim


class TauriShimSecurityTests(unittest.TestCase):
    def test_generated_shim_contains_no_embedded_api_credentials(self) -> None:
        shim = get_tauri_shim(7777, r"C:\Users\Test").decode("utf-8")

        self.assertNotIn("ag-local-token", shim)
        self.assertNotIn("AUTH_TOKEN", shim)
        self.assertNotIn("'Authorization': 'Bearer '", shim)
        self.assertIn("7777", shim)
        self.assertIn(r"C:\\Users\\Test", shim)

    def test_retry_keeps_existing_browser_storage(self) -> None:
        shim = get_tauri_shim(7777, r"C:\Users\Test").decode("utf-8")
        self.assertNotIn('localStorage.clear()', shim)
        self.assertNotIn('sessionStorage.clear()', shim)


if __name__ == "__main__":
    unittest.main()
