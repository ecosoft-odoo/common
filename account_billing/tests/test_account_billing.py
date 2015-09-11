# -*- coding: utf-8 -*-
#
#    Author: Kitti Upariphutthiphong
#    Copyright 2014-2015 Ecosoft Co., Ltd.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#

import time
import openerp.tests.common as common


class TestAccountBilling(common.TransactionCase):

    # 1. Create Billing Document, EUR, dated 17 this month.
    # 2. Validate, only 1 line created, amount equal to 500 EUR.
    # 3. Billed It.
    # 4. Create Payment, whatever the date is, choose Billing ID
    # 5. Amount equal to the billing

    def setUp(self):
        super(TestAccountBilling, self).setUp()
        self.company_model = self.env['res.company']
        self.bill_model = self.env['account.billing']
        self.partner_model = self.env['res.partner']
        self.partner_id = self.ref('base.res_partner_14')
        self.journal_id = self.ref('account.sales_journal')
        self.date = time.strftime('%Y-%m') + '-17'
        self.company_id = \
            self.company_model._company_default_get('account.billing')

    def test_normal_case(self):
        res = self.bill_model.onchange_journal(self.journal_id,
                                               self.partner_id,
                                               self.date,
                                               self.company_id)
        invoices = res['value']['line_cr_ids']
        billing_amount = res['value']['billing_amount']
        self.assertEqual(len(invoices), 1)
        self.assertEqual(billing_amount, 500)  # Amount equal to invoice_1
        
