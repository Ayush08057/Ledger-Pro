import unittest
from app.server import app

class TestTallyF11F12Authenticity(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_f11_features_api_and_persistence(self):
        # 1. Fetch current features
        res = self.client.get('/api/company/features')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('features', data)
        feats = data['features']
        self.assertIn('maintain_accounts', feats)
        self.assertIn('enable_gst', feats)

        # 2. Update features via POST
        res_post = self.client.post('/api/company/features', json={
            'maintain_accounts': 'Yes',
            'enable_cost_centres': 'Yes',
            'enable_batches': 'Yes'
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json().get('success'))

        # 3. Verify persistence
        res_verify = self.client.get('/api/company/features')
        data_verify = res_verify.get_json()
        feats_verify = data_verify['features']
        self.assertEqual(feats_verify.get('enable_cost_centres'), 'Yes')
        self.assertEqual(feats_verify.get('enable_batches'), 'Yes')

    def test_f12_voucher_config_api_and_persistence(self):
        # 1. Fetch current config
        res = self.client.get('/api/voucher/config')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('config', data)

        # 2. Update config via POST
        res_post = self.client.post('/api/voucher/config', json={
            'use_dr_cr': 'Yes',
            'show_current_balance': 'Yes',
            'warn_negative_cash': 'Yes'
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json().get('success'))

        # 3. Verify persistence
        res_verify = self.client.get('/api/voucher/config')
        cfg = res_verify.get_json()['config']
        self.assertEqual(cfg.get('use_dr_cr'), 'Yes')
        self.assertEqual(cfg.get('show_current_balance'), 'Yes')
        self.assertEqual(cfg.get('warn_negative_cash'), 'Yes')

    def test_f11_ui_authenticity_in_base_template(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Authentic Tally toggle rows must be present
        self.assertIn('tally-toggle-row', html)
        self.assertIn('row_feat_maintain_accounts', html)
        self.assertIn('row_feat_enable_gst', html)
        self.assertIn('row_feat_enable_cost_centres', html)
        self.assertIn('feat_val_show_more', html)
        self.assertIn('feat_val_show_all', html)

        # Generic select dropdowns in F11 MUST be gone
        self.assertNotIn('select id="feat_', html)

        # Keyboard controllers must be present
        self.assertIn('handleF11ModalKeyboard', html)
        self.assertIn('setFeatureValue', html)
        self.assertIn('toggleFeatureRow', html)
        self.assertIn('updateFeatureDependencies', html)

    def test_f12_ui_authenticity_in_voucher_template(self):
        res = self.client.get('/vouchers/create?type=Payment')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Authentic Tally toggle rows in F12 voucher config modal
        self.assertIn('row_vcfg_use_dr_cr', html)
        self.assertIn('row_vcfg_show_current_balance', html)
        self.assertIn('row_vcfg_warn_negative_cash', html)
        self.assertIn('vcfg_val_show_more', html)

        # Generic select dropdowns in F12 MUST be gone
        self.assertNotIn('select id="vcfg_', html)

        # Keyboard controllers for F12 voucher modal
        self.assertIn('handleF12VoucherModalKeyboard', html)
        self.assertIn('setVoucherConfigValue', html)
        self.assertIn('openF12VoucherModal', html)
        self.assertIn('openF12Modal', html)
        self.assertIn('tally-toggle-sub', html)
        self.assertIn('row_vcfg_bank_default_allocations', html)
        self.assertIn('row_vcfg_pg_default_allocations', html)

    def test_daybook_authenticity_and_bottom_bar(self):
        res = self.client.get('/daybook')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Verified authentic Tally bottom actions
        self.assertIn('Enter</strong>: Alter', html)
        self.assertIn('Space</strong>: Select', html)
        self.assertIn('A</strong>: Add Vch', html)
        self.assertIn('D</strong>: Delete', html)
        self.assertIn('X</strong>: Cancel Vch', html)

    def test_f12_btnbar_and_general_config_modal(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # 1. Right Button Bar MUST contain F10 Other Vch and F12 Configure
        self.assertIn('>F12<', html)
        self.assertIn('>Configure<', html)
        self.assertIn('>F10<', html)
        self.assertIn('>Other Vch<', html)
        self.assertIn('btnbar_f12', html)

        # 2. General F12 modal MUST contain all detailed Debit & Credit options
        self.assertIn('row_gcfg_use_dr_cr', html)
        self.assertIn('row_gcfg_warn_negative_cash', html)
        self.assertIn('row_gcfg_show_current_balance', html)
        self.assertIn('row_gcfg_skip_date_field', html)
        self.assertIn('row_gcfg_show_bill_wise_details', html)
        self.assertIn('row_gcfg_show_list_of_bills', html)
        self.assertIn('row_gcfg_show_final_balances_bills', html)
        self.assertIn('row_gcfg_provide_supplier_ref', html)
        self.assertIn('row_gcfg_warn_voucher_no_16', html)

        # 3. Controllers and handlers present
        self.assertIn('openGeneralConfigModal', html)
        self.assertIn('saveGeneralConfigModal', html)
        self.assertIn('handleGeneralConfigModalKeyboard', html)
        self.assertIn('triggerF12Action', html)

if __name__ == '__main__':
    unittest.main()
