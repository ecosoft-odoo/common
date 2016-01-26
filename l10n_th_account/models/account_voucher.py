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

import datetime
import time
from openerp import models, fields, api, _
from openerp.exceptions import except_orm
import openerp.addons.decimal_precision as dp


class common_voucher(object):

    @api.model
    def _to_invoice_currency(self, invoice, journal, amount):
        currency = invoice.currency_id.with_context(
            date=invoice.date_invoice or
            datetime.datetime.today())
        company_currency = (journal.currency and
                            journal.currency.id or
                            journal.company_id.currency_id)
        amount = currency.compute(float(amount), company_currency, round=False)
        return amount

    @api.model
    def _to_voucher_currency(self, invoice, journal, amount):
        currency = invoice.currency_id.with_context(
            date=invoice.date_invoice or
            datetime.datetime.today())
        company_currency = (journal.currency and
                            journal.currency.id or
                            journal.company_id.currency_id)
        amount = currency.compute(float(amount), company_currency, round=False)
        return amount


class account_voucher(common_voucher, models.Model):

    _inherit = 'account.voucher'

    # Columns
    tax_line = fields.One2many(
        'account.voucher.tax',
        'voucher_id',
        string='Tax Lines',
        readonly=False)

    @api.model
    def _compute_writeoff_amount(self,
                                 line_dr_ids,
                                 line_cr_ids,
                                 amount, _type):
        res = super(account_voucher, self)._compute_writeoff_amount(
            line_dr_ids,
            line_cr_ids,
            amount, _type)
        debit = credit = 0.0
        sign = _type == 'payment' and -1 or 1
        for l in line_dr_ids:
            if isinstance(l, dict):
                debit += l.get('amount_wht', 0.0) + \
                    l.get('amount_retention', 0.0)  # Added
        for l in line_cr_ids:
            if isinstance(l, dict):
                credit += l.get('amount_wht', 0.0) + \
                    l.get('amount_retention', 0.0)  # Added
        return res - sign * (credit - debit)

    # Note: This method is not exactly the same as the line's one.
    @api.model
    def _get_amount_wht_ex(self, partner_id, move_line_id, amount_original,
                           original_wht_amt, original_retention_amt, amount):
        tax_obj = self.env['account.tax']
        partner_obj = self.env['res.partner']
        move_line_obj = self.env['account.move.line']
        partner = partner_obj.browse(partner_id)
        move_line = move_line_obj.browse(move_line_id)
        amount_wht = 0.0
        if move_line.invoice:
            invoice = move_line.invoice
            for line in invoice.invoice_line:
                revised_price = line.price_unit * \
                    (1 - (line.discount or 0.0) / 100.0)
                # Only WHT
                is_wht = True in [x.is_wht
                                  for x in
                                  line.invoice_line_tax_id] or False
                if is_wht:
                    new_amt_orig = (amount_original -
                                    original_wht_amt -
                                    original_retention_amt)
                    ratio = (new_amt_orig and amount / new_amt_orig or 0.0)
                    taxes_list = line.invoice_line_tax_id.compute_all(
                        revised_price * ratio,
                        line.quantity,
                        line.product_id,
                        partner)['taxes']
                    for tax in taxes_list:
                        account_tax = tax_obj.browse(tax['id'])
                        if account_tax.is_wht:
                            # Check Threshold
                            base = revised_price * line.quantity
                            t = account_tax.read(['threshold_wht'])
                            if abs(base) and abs(base) < t[0]['threshold_wht']:
                                continue
                            amount_wht += tax['amount']
            # Convert to voucher currency
            amount_wht = self._to_voucher_currency(invoice,
                                                   move_line.journal_id,
                                                   amount_wht)
        return float(amount), float(amount_wht)

    # Note: This method is not exactly the same as the line's one.
    @api.model
    def _get_amount_retention_ex(self, partner_id, move_line_id,
                                 amount_original, original_retention_amt,
                                 original_wht_amt, amount):
        move_line_obj = self.env['account.move.line']
        move_line = move_line_obj.browse(move_line_id)
        amount_retention = 0.0
        if move_line.invoice:
            invoice = move_line.invoice
            if invoice.retention_on_payment:
                # Here is what different from _get_amount_retention()
                new_amt_orig = (amount_original -
                                original_retention_amt -
                                original_wht_amt)
                ratio = (new_amt_orig and amount / new_amt_orig or 0.0)
                amount_retention = invoice.amount_retention * ratio
                # Change to currency at invoicing time.
                amount_retention = self._to_voucher_currency(
                    invoice,
                    move_line.journal_id,
                    amount_retention)
        return float(amount), float(amount_retention)

    # The original recompute_voucher_lines() do not aware of withholding.
    # Here we will re-adjust it. As such, the amount allocation will be reduced
    # and carry to the next lines.
    @api.multi
    def recompute_voucher_lines(self, partner_id, journal_id,
                                price, currency_id, ttype, date):
        res = super(account_voucher, self).recompute_voucher_lines(
            partner_id, journal_id,
            price, currency_id, ttype, date)
        line_cr_ids = res['value']['line_cr_ids']
        line_dr_ids = res['value']['line_dr_ids']
        # For Register Payment on Invoice, remove
        sign = 0
        move_line_obj = self.env['account.move.line']
        remain_amount = float(price)
        if ttype == 'payment':
            lines = line_cr_ids + line_dr_ids
        else:
            lines = line_dr_ids + line_cr_ids
        active_cr_lines, active_dr_lines = [], []
        for line in lines:
            if not isinstance(line, dict):
                continue
            amount, amount_wht, amount_retention = 0.0, 0.0, 0.0
            move_line = move_line_obj.browse(line['move_line_id'])
            invoice_id = self._context.get('invoice_id', False)
            if invoice_id and move_line.invoice.id != invoice_id:
                continue
            # Test to get full wht, retention first
            line_obj = self.env['account.voucher.line']
            original_amount, \
                original_wht_amt = line_obj._get_amount_wht(
                    partner_id,
                    line['move_line_id'],
                    line['amount_original'],
                    line['amount_original'])
            original_amount, \
                original_retention_amt = line_obj._get_amount_retention(
                    partner_id,
                    line['move_line_id'],
                    line['amount_original'],
                    line['amount_original'])
            # Full amount to reconcile
            new_amt_orig = (original_amount -
                            original_wht_amt -
                            original_retention_amt)
            ratio = original_amount > 0.0 and \
                new_amt_orig / original_amount or 0.0
            amount_alloc = line['amount_unreconciled'] * ratio
            # Allocations Amount
            if ttype == 'payment':  # Supplier Payment
                if line['type'] == 'cr':  # always full allocation.
                    sign = 1
                    amount_alloc = amount_alloc
                else:  # cr, spend the remaining
                    sign = -1
                    if remain_amount == 0.0:
                        amount_alloc = 0.0
                    else:
                        if 'default_amount' in self._context:  # Case Dialog
                            amount_alloc = amount_alloc
                        else:
                            amount_alloc = amount_alloc > remain_amount and \
                                remain_amount or amount_alloc
            else:  # Customer Payment
                if line['type'] == 'dr':  # always full allocation.
                    sign = 1
                    amount_alloc = amount_alloc
                else:  # cr, spend the remaining
                    sign = -1
                    if remain_amount == 0.0:
                        amount_alloc = 0.0
                    else:
                        if 'default_amount' in self._context:  # Case Dialog
                            amount_alloc = amount_alloc
                        else:
                            amount_alloc = amount_alloc > remain_amount and \
                                remain_amount or amount_alloc
            # ** Calculate withholding amount **
            if amount_alloc:
                amount, amount_wht = self._get_amount_wht_ex(
                    partner_id,
                    line['move_line_id'],
                    line['amount_original'],
                    original_wht_amt,
                    original_retention_amt,
                    amount_alloc)
                amount, amount_retention = self._get_amount_retention_ex(
                    partner_id,
                    line['move_line_id'],
                    line['amount_original'],
                    original_retention_amt,
                    original_wht_amt,
                    amount_alloc)
            # Adjust remaining
            remain_amount = remain_amount + (sign * amount_alloc)
            line['amount'] = amount + amount_wht + amount_retention
            line['amount_wht'] = -amount_wht
            line['amount_retention'] = -amount_retention
            line['reconcile'] = line['amount'] == line['amount_unreconciled']
            if line['type'] == 'cr':
                active_cr_lines.append(line)
            if line['type'] == 'dr':
                active_dr_lines.append(line)
        # For case Register Payment form invoice, remove zero amount lines
        if 'default_amount' in self._context:
            res['value']['line_cr_ids'] = active_cr_lines
            res['value']['line_dr_ids'] = active_dr_lines
        return res

    @api.multi
    def button_reset_taxes(self):
        for voucher in self:
            if voucher.state == 'posted':
                continue
            self._cr.execute("""
                DELETE FROM account_voucher_tax
                WHERE voucher_id=%s AND manual is False
                """, (voucher.id,))
            partner = voucher.partner_id
            if partner.lang:
                voucher.with_context(lang=partner.lang)
            voucher_tax_obj = self.env['account.voucher.tax']
            for tax in voucher_tax_obj.compute(voucher).values():
                voucher_tax_obj.create(tax)
        return True

    @api.multi
    def write(self, vals):
        """ automatic compute tax then save """
        res = super(account_voucher, self).write(vals)
        # When editing only tax amount, do not reset tax
        to_update = True
        if vals.get('tax_line', False):
            for tax_line in vals.get('tax_line'):
                if tax_line[0] == 1 and 'amount' in tax_line[2]:  # 1 = update
                    to_update = False
        if to_update:
            self.button_reset_taxes()
        return res

    @api.v7
    def action_move_line_create(self, cr, uid, ids, context=None):
        """ Overwrite, all change marked with 'ecosoft' """
        '''
        Confirm the vouchers given in ids and create the
        journal entries for each of them
        '''
        if context is None:
            context = {}
        move_pool = self.pool.get('account.move')
        move_line_pool = self.pool.get('account.move.line')
        for voucher in self.browse(cr, uid, ids, context=context):
            local_context = dict(
                context,
                force_company=voucher.journal_id.company_id.id)
            if voucher.move_id:
                continue
            company_currency = self._get_company_currency(cr, uid,
                                                          voucher.id, context)
            current_currency = self._get_current_currency(cr, uid,
                                                          voucher.id, context)
            # we select the context to use accordingly if
            # it's a multicurrency case or not
            context = self._sel_context(cr, uid, voucher.id, context)
            # But for the operations made by _convert_amount, we always
            # need to give the date in the context
            ctx = context.copy()
            ctx.update({'date': voucher.date})
            # Create the account move record.
            move_id = move_pool.create(cr, uid,
                                       self.account_move_get(
                                           cr, uid,
                                           voucher.id, context=context),
                                       context=context)
            # Get the name of the account_move just created
            name = move_pool.browse(cr, uid, move_id, context=context).name
            # Create the first line of the voucher
            move_line_id = move_line_pool.create(
                cr, uid,
                self.first_move_line_get(
                    cr, uid, voucher.id,
                    move_id, company_currency,
                    current_currency, local_context),
                local_context)
            move_line_brw = move_line_pool.browse(cr, uid,
                                                  move_line_id,
                                                  context=context)
            line_total = move_line_brw.debit - move_line_brw.credit
            rec_list_ids = []
            # ecosoft
            net_tax = 0.0
            net_retention = 0.0
            # --
            if voucher.type == 'sale':
                line_total = line_total - self._convert_amount(
                    cr, uid,
                    voucher.tax_amount,
                    voucher.id, context=ctx)
            elif voucher.type == 'purchase':
                line_total = line_total + self._convert_amount(
                    cr, uid,
                    voucher.tax_amount,
                    voucher.id, context=ctx)
            # ecosoft
            elif voucher.type in ('receipt', 'payment'):
                net_tax = self.voucher_move_line_tax_create(
                    cr, uid, voucher,
                    move_id, company_currency,
                    current_currency, context)
                net_retention = self.voucher_move_line_retention_create(
                    cr, uid, voucher,
                    move_id, company_currency,
                    current_currency, context)
            # --
            # Create one move line per voucher line where amount is not 0.0
            line_total, rec_list_ids = self.voucher_move_line_create(
                cr, uid,
                voucher.id, line_total,
                move_id, company_currency,
                current_currency, context)
            # ecosoft - Thai Accounting, adjust with tax before writeoff.
            line_total = line_total + net_tax + net_retention
            # --
            # Create the writeoff line if needed
            ml_writeoff = self.writeoff_move_line_get(
                cr, uid,
                voucher.id, line_total, move_id,
                name, company_currency,
                current_currency, local_context)
            if ml_writeoff:
                move_line_pool.create(cr, uid, ml_writeoff, local_context)
            # We post the voucher.
            self.write(cr, uid, [voucher.id], {
                'move_id': move_id,
                'state': 'posted',
                'number': name,
            })
            if voucher.journal_id.entry_posted:
                move_pool.post(cr, uid, [move_id], context={})
            # We automatically reconcile the account move lines.
            # reconcile = False (not in use when refactor)
            for rec_ids in rec_list_ids:
                if len(rec_ids) >= 2:
                    move_line_pool.reconcile_partial(
                        cr, uid,
                        rec_ids, writeoff_acc_id=voucher.writeoff_acc_id.id,
                        writeoff_period_id=voucher.period_id.id,
                        writeoff_journal_id=voucher.journal_id.id)
        return True

    @api.model
    def voucher_move_line_tax_create(self, voucher, move_id,
                                     company_currency, current_currency):
        """ New Method for account.voucher.tax """
        move_line_obj = self.env['account.move.line']
        avt_obj = self.env['account.voucher.tax']
        # one move line per tax line
        vtml = avt_obj.move_line_get(voucher.id)
        # create gain/loss from currency between invoice and voucher
        vtml = self.compute_tax_currency_gain(voucher, vtml)
        # create one move line for the total and adjust the other lines amount
        net_tax_currency, vtml = self.compute_net_tax(voucher,
                                                      company_currency,
                                                      vtml)
        # Create move line,
        for ml in vtml:
            ml.update({'move_id': move_id})
            move_line_obj.create(ml)
        return net_tax_currency

    @api.model
    def voucher_move_line_retention_create(self, voucher, move_id,
                                           company_currency, current_currency):
        """ New Method for Retention """
        move_line_obj = self.env['account.move.line']
        # one move line per retention line
        vtml = self.move_line_get(voucher)
        # create gain/loss from currency between invoice and voucher
        net_retention_currency, vtml = self.compute_net_retention(
            voucher, company_currency, vtml)
        # Create move line,
        for ml in vtml:
            ml.update({'move_id': move_id})
            move_line_obj.create(ml)
        return net_retention_currency

    @api.model
    def move_line_get(self, voucher):
        res = []
        self._cr.execute("""
            SELECT * FROM account_voucher_line
            WHERE voucher_id=%s and amount_retention != 0""", (voucher.id,))
        for t in self._cr.dictfetchall():
            prop = voucher.type in ('sale', 'purchase') \
                and self.env['ir.property'].get(
                'property_account_retention_customer', 'res.partner') \
                or self.env['ir.property'].get(
                'property_account_retention_supplier', 'res.partner')
            account = self.env['account.fiscal.position'].map_account(prop)
            res.append({
                'type': 'src',
                'name': _('Retention Amount'),
                'price_unit': t['amount_retention'],
                'quantity': 1,
                'price': t['amount_retention'],
                'account_id': account.id,
                'product_id': False,
                'uos_id': False,
                'account_analytic_id': False,
                'taxes': False,
            })
        return res

    @api.model
    def compute_net_tax(self, voucher,
                        company_currency,
                        voucher_tax_move_lines):
        """ New Method to compute the net tax (cr/dr) """
        total = 0
        total_currency = 0
        cur_obj = self.env['res.currency']
        current_currency = self._get_current_currency(voucher.id)
        for i in voucher_tax_move_lines:
            if current_currency != company_currency:
                date = voucher.date or time.strftime('%Y-%m-%d')
                cur_obj.with_context(date=date)
                i['currency_id'] = current_currency
                i['amount_currency'] = i['price']
                i['price'] = cur_obj.compute(current_currency,
                                             company_currency,
                                             i['price'])
            else:
                i['amount_currency'] = False
                i['currency_id'] = False
            debit = credit = 0.0
            if voucher.type == 'payment':
                debit = i['amount_currency'] or i['price']
                total += i['price']
                total_currency += i['amount_currency'] or i['price']
            else:
                credit = i['amount_currency'] or i['price']
                total -= i['price']
                total_currency -= i['amount_currency'] or i['price']
                i['price'] = - i['price']
            if debit < 0:
                credit = -debit
                debit = 0.0
            if credit < 0:
                debit = -credit
                credit = 0.0
            i['period_id'] = voucher.period_id.id
            i['partner_id'] = voucher.partner_id.id
            i['date'] = voucher.date
            i['date_maturity'] = voucher.date_due
            i['debit'] = debit
            i['credit'] = credit
        return total_currency, voucher_tax_move_lines

    @api.model
    def compute_net_retention(self, voucher,
                              company_currency,
                              voucher_retention_move_lines):
        """ New Method to compute the net tax (cr/dr) """
        total = 0
        total_currency = 0
        cur_obj = self.env['res.currency']
        current_currency = self._get_current_currency(voucher.id)
        for i in voucher_retention_move_lines:
            if current_currency != company_currency:
                date = voucher.date or time.strftime('%Y-%m-%d')
                cur_obj.with_context(date=date)
                i['currency_id'] = current_currency
                i['amount_currency'] = i['price']
                i['price'] = cur_obj.compute(current_currency,
                                             company_currency,
                                             i['price'])
            else:
                i['amount_currency'] = False
                i['currency_id'] = False
            debit = credit = 0.0
            if voucher.type == 'payment':
                debit = i['amount_currency'] or i['price']
                total += i['price']
                total_currency += i['amount_currency'] or i['price']
            else:
                credit = i['amount_currency'] or i['price']
                total -= i['price']
                total_currency -= i['amount_currency'] or i['price']
                i['price'] = - i['price']
            if debit < 0:
                credit = -debit
                debit = 0.0
            if credit < 0:
                debit = -credit
                credit = 0.0
            i['period_id'] = voucher.period_id.id
            i['partner_id'] = voucher.partner_id.id
            i['date'] = voucher.date
            i['date_maturity'] = voucher.date_due
            i['debit'] = debit
            i['credit'] = credit
        return total_currency, voucher_retention_move_lines

    @api.model
    def compute_tax_currency_gain(self, voucher, voucher_tax_move_lines):
        """ New Method to add gain loss from currency for tax """
        for i in voucher_tax_move_lines:
            if 'tax_currency_gain' in i and i['tax_currency_gain']:
                debit = credit = 0.0
                if voucher.type == 'payment':
                    debit = i['tax_currency_gain']
                else:
                    credit = i['tax_currency_gain']
                if debit < 0:
                    credit = -debit
                    debit = 0.0
                if credit < 0:
                    debit = -credit
                    credit = 0.0
                gain_account_id, loss_account_id = False, False
                company = voucher.company_id
                income_acct = company.income_currency_exchange_account_id
                expense_acct = company.expense_currency_exchange_account_id
                if income_acct and expense_acct:
                    gain_account_id = income_acct.id
                    loss_account_id = expense_acct.id
                else:
                    raise except_orm(
                        _('Error!'),
                        _('No gain/loss accounting defined in the system!'))
                if debit > 0.0 or credit > 0.0:
                    sign = debit - credit < 0 and -1 or 1
                    voucher_tax_move_lines.append({
                        'type': 'tax',
                        'name': _('Gain/Loss Exchange Rate'),
                        'quantity': 1,
                        'price': sign * (credit or -debit),
                        'account_id': (credit and
                                       gain_account_id or
                                       loss_account_id)
                    })
        return voucher_tax_move_lines

    @api.multi
    def onchange_journal(self, journal_id, line_ids, tax_id, partner_id,
                         date, amount, ttype, company_id):
        res = super(account_voucher, self).onchange_journal(
            journal_id, line_ids, tax_id, partner_id,
            date, amount, ttype, company_id)
        if 'default_amount' in self._context and res:
            vline_obj = self.env['account.voucher.line']
            if amount == 0.0:  # Sum amount for the line to reconcile
                lines = ['line_cr_ids', 'line_dr_ids']
                for line in lines:
                    for l in res['value'].get(line, []):
                        val = vline_obj.onchange_reconcile(
                            partner_id,
                            l['move_line_id'], l['amount_original'],
                            True, l['amount'], l['amount_unreconciled'])
                        amount += (val['value']['amount'] +
                                   val['value']['amount_wht'] +
                                   val['value']['amount_retention'])
                # Reverse sign for refund
                if self._context.get('invoice_type') in \
                        ('out_refund', 'in_refund'):
                    amount = -amount
                res['value'].update({'amount': amount})
        return res


class account_voucher_line(common_voucher, models.Model):

    _inherit = 'account.voucher.line'

    amount_wht = fields.Float(
        string='WHT',
        digits_compute=dp.get_precision('Account'))
    amount_retention = fields.Float(
        string='Retention',
        digits_compute=dp.get_precision('Account'))
    retention_on_payment = fields.Boolean(
        string='Retention on Payment',
        related='move_line_id.invoice.retention_on_payment',
        store=True,
        readonly=True)

    @api.model
    def _get_amount_wht(self, partner_id, move_line_id,
                        amount_original, amount):
        tax_obj = self.env['account.tax']
        partner_obj = self.env['res.partner']
        move_line_obj = self.env['account.move.line']
        partner = partner_obj.browse(partner_id)
        move_line = move_line_obj.browse(move_line_id)
        amount_wht = 0.0
        if move_line.invoice:
            invoice = move_line.invoice
            for line in invoice.invoice_line:
                revised_price = (line.price_unit *
                                 (1 - (line.discount or 0.0) / 100.0))
                # Only WHT
                is_wht = True in [x.is_wht
                                  for x in
                                  line.invoice_line_tax_id] or False
                if is_wht:
                    ratio = (float(amount_original) and
                             (float(amount) / float(amount_original)) or 0.0)
                    tax_list = line.invoice_line_tax_id.compute_all(
                        float(revised_price) * ratio,
                        line.quantity,
                        line.product_id,
                        partner)['taxes']
                    for tax in tax_list:
                        account_tax = tax_obj.browse(tax['id'])
                        if account_tax.is_wht:
                            amount_wht += tax['amount']

            # Change to currency at invoicing time.
            amount_wht = self._to_voucher_currency(invoice,
                                                   move_line.journal_id,
                                                   amount_wht,)
        return float(amount), float(amount_wht)

    @api.model
    def _get_amount_retention(self, partner_id,
                              move_line_id, amount_original, amount):
        move_line_obj = self.env['account.move.line']
        move_line = move_line_obj.browse(move_line_id)
        amount_retention = 0.0
        if move_line.invoice:
            invoice = move_line.invoice
            if invoice.retention_on_payment:
                ratio = (float(amount_original) and
                         (float(amount) / float(amount_original)) or 0.0)
                amount_retention = invoice.amount_retention * ratio
                # Change to currency at invoicing time.
                amount_retention = self._to_voucher_currency(
                    invoice,
                    move_line.journal_id,
                    amount_retention)
        return float(amount), float(amount_retention)

    @api.multi
    def onchange_amount(self, partner_id, move_line_id,
                        amount_original, amount, amount_unreconciled):
        vals = {}
        prec = self.env['decimal.precision'].precision_get('Account')
        amount, amount_wht = self._get_amount_wht(
            partner_id,
            move_line_id,
            amount_original,
            amount)
        amount, amount_retention = self._get_amount_retention(
            partner_id,
            move_line_id,
            amount_original,
            amount)
        vals['amount_wht'] = -round(amount_wht, prec)
        vals['amount_retention'] = -round(amount_retention, prec)
        vals['reconcile'] = (round(amount) == round(amount_unreconciled))
        return {'value': vals}

    @api.multi
    def onchange_reconcile(self, partner_id, move_line_id, amount_original,
                           reconcile, amount, amount_unreconciled):
        vals = {}
        prec = self.env['decimal.precision'].precision_get('Account')
        if reconcile:
            amount = amount_unreconciled
            amount, amount_wht = self._get_amount_wht(
                partner_id,
                move_line_id,
                amount_original,
                amount)
            amount, amount_retention = self._get_amount_retention(
                partner_id,
                move_line_id,
                amount_original,
                amount)
            vals['amount_wht'] = -round(amount_wht, prec)
            vals['amount_retention'] = -round(amount_retention, prec)
            vals['amount'] = round(amount, prec)
        return {'value': vals}


class account_voucher_tax(common_voucher, models.Model):

    _name = "account.voucher.tax"
    _description = "Voucher Tax"
    _order = 'sequence,invoice_id,name'

    @api.one
    @api.depends('tax_amount', 'amount')
    def _count_factor(self):
        self.factor_tax = (self.amount != 0.0 and
                           self.tax_amount / self.amount or 1.0)
        self.factor_base = (self.base != 0.0 and
                            self.base_amount / self.base or 1.0)

    voucher_id = fields.Many2one(
        'account.voucher',
        string='Voucher',
        ondelete='cascade',
        select=True)
    invoice_id = fields.Many2one(
        'account.invoice',
        string='Invoice')
    tax_id = fields.Many2one(
        'account.tax',
        string='Tax')
    name = fields.Char(
        string='Tax Description',
        size=64,
        required=True)
    account_id = fields.Many2one(
        'account.account',
        string='Tax Account',
        required=True,
        domain=[('type', 'not in', ('view', 'income', 'closed'))])
    account_analytic_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic account')
    base = fields.Float(
        string='Base',
        digits_compute=dp.get_precision('Account'))
    amount = fields.Float(
        string='Amount',
        digits_compute=dp.get_precision('Account'))
    tax_currency_gain = fields.Float(
        string='Currency Gain',
        digits_compute=dp.get_precision('Account'))
    manual = fields.Boolean(
        string='Manual',
        default=True)
    sequence = fields.Integer(
        string='Sequence',
        help="Sequence order when displaying a list of voucher tax.")
    base_code_id = fields.Many2one(
        'account.tax.code',
        string='Base Code',
        help="The account basis of the tax declaration.")
    base_amount = fields.Float(
        string='Base Code Amount',
        digits_compute=dp.get_precision('Account'),
        default=0.0)
    tax_code_id = fields.Many2one(
        'account.tax.code',
        string='Tax Code',
        help="The tax basis of the tax declaration.")
    tax_amount = fields.Float(
        string='Tax Code Amount',
        digits_compute=dp.get_precision('Account'),
        default=0.0)
    company_id = fields.Many2one(
        'res.company',
        related='account_id.company_id',
        string='Company',
        store=True,
        readonly=True)
    factor_base = fields.Float(
        string='Multipication factor for Base code',
        compute='_count_factor')
    factor_tax = fields.Float(
        string='Multipication factor Tax code',
        compute='_count_factor')

    @api.model
    def _compute_one_tax_grouped(self, taxes, voucher, voucher_cur,
                                 invoice, invoice_cur, company_currency,
                                 journal, line_sign, payment_ratio,
                                 line, revised_price):
        tax_gp = {}
        tax_obj = self.env['account.tax']

        for tax in taxes:
            # For Normal
            val = {}
            val['voucher_id'] = voucher.id
            val['invoice_id'] = invoice.id
            val['tax_id'] = tax['id']
            val['name'] = tax['name']
            val['amount'] = self._to_voucher_currency(
                invoice, journal,
                (tax['amount'] *
                 payment_ratio *
                 line_sign))
            val['manual'] = False
            val['sequence'] = tax['sequence']
            val['base'] = self._to_voucher_currency(
                invoice, journal,
                voucher_cur.round(
                    tax['price_unit'] * line.quantity) *
                payment_ratio * line_sign)
            # For Suspend
            vals = {}
            vals['voucher_id'] = voucher.id
            vals['invoice_id'] = invoice.id
            vals['tax_id'] = tax['id']
            vals['name'] = tax['name']
            vals['amount'] = self._to_invoice_currency(
                invoice, journal,
                (-tax['amount'] *
                 payment_ratio *
                 line_sign))
            vals['manual'] = False
            vals['sequence'] = tax['sequence']
            vals['base'] = self._to_invoice_currency(
                invoice, journal,
                -voucher_cur.round(
                    tax['price_unit'] * line.quantity) *
                payment_ratio * line_sign)

            # Register Currency Gain for Normal
            val['tax_currency_gain'] = -(val['amount'] + vals['amount'])
            vals['tax_currency_gain'] = 0.0

            # Check the if services, which has been using suspend account
            # This time, it needs to cr: non-suspend acct and dr: suspend acct
            tax1 = tax_obj.browse(tax['id'])
            use_suspend_acct = tax1.is_suspend_tax
            is_wht = tax1.is_wht
            # -------------------> Adding Tax for Posting
            if is_wht:
                # Check Threshold first
                base = invoice_cur.compute((revised_price * line.quantity),
                                           company_currency)
                t = tax_obj.browse(val['tax_id'])
                if abs(base) and abs(base) < t.threshold_wht:
                    continue
                # Case Withholding Tax Dr.
                if voucher.type in ('receipt', 'payment'):
                    val['base_code_id'] = tax['base_code_id']
                    val['tax_code_id'] = tax['tax_code_id']
                    val['base_amount'] = voucher_cur.compute(
                        val['base'] *
                        tax['base_sign'],
                        company_currency) * payment_ratio
                    val['tax_amount'] = voucher_cur.compute(
                        val['amount'] *
                        tax['tax_sign'],
                        company_currency) * payment_ratio
                    val['account_id'] = (tax['account_collected_id'] or
                                         line.account_id.id)
                    val['account_analytic_id'] = \
                        tax['account_analytic_collected_id']
                else:
                    val['base_code_id'] = tax['ref_base_code_id']
                    val['tax_code_id'] = tax['ref_tax_code_id']
                    val['base_amount'] = voucher_cur.compute(
                        val['base'] *
                        tax['ref_base_sign'],
                        company_currency) * payment_ratio
                    val['tax_amount'] = voucher_cur.compute(
                        val['amount'] *
                        tax['ref_tax_sign'],
                        company_currency) * payment_ratio
                    val['account_id'] = (tax['account_paid_id'] or
                                         line.account_id.id)
                    val['account_analytic_id'] = \
                        tax['account_analytic_paid_id']

                if not val.get('account_analytic_id', False) and \
                        line.account_analytic_id and \
                        val['account_id'] == line.account_id.id:
                    val['account_analytic_id'] = line.account_analytic_id.id

                key = (val['tax_code_id'],
                       val['base_code_id'],
                       val['account_id'])
                if not (key in tax_gp):
                    tax_gp[key] = val
                    tax_gp[key]['amount'] = -tax_gp[key]['amount']
                    tax_gp[key]['base'] = -tax_gp[key]['base']
                    tax_gp[key]['base_amount'] = -tax_gp[key]['base_amount']
                    tax_gp[key]['tax_amount'] = -tax_gp[key]['tax_amount']
                    tax_gp[key]['tax_currency_gain'] = 0.0  # No gain for WHT
                else:
                    tax_gp[key]['amount'] -= val['amount']
                    tax_gp[key]['base'] -= val['base']
                    tax_gp[key]['base_amount'] -= val['base_amount']
                    tax_gp[key]['tax_amount'] -= val['tax_amount']
                    tax_gp[key]['tax_currency_gain'] -= 0.0  # No gain for WHT

            # --> Adding Tax for Posting 1) Contra-Suspend 2) Non-Suspend
            elif use_suspend_acct:
                # First: Do the Cr: with Non-Suspend Account
                refer_tax = tax_obj.browse(val['tax_id']).refer_tax_id
                # Change name to refer_tax_id
                vals['name'] = tax1.refer_tax_id.name
                if voucher.type in ('receipt', 'payment'):
                    val['tax_id'] = refer_tax and refer_tax.id or val['tax_id']
                    val['base_code_id'] = tax['base_code_id']
                    val['tax_code_id'] = tax['tax_code_id']
                    val['base_amount'] = voucher_cur.compute(
                        val['base'] *
                        tax['base_sign'],
                        company_currency) * payment_ratio
                    val['tax_amount'] = voucher_cur.compute(
                        val['amount'] *
                        tax['tax_sign'],
                        company_currency) * payment_ratio
                    val['account_id'] = (tax['account_collected_id'] or
                                         line.account_id.id)
                    val['account_analytic_id'] = \
                        tax['account_analytic_collected_id']
                else:
                    val['tax_id'] = refer_tax and refer_tax.id or val['tax_id']
                    val['base_code_id'] = tax['ref_base_code_id']
                    val['tax_code_id'] = tax['ref_tax_code_id']
                    val['base_amount'] = voucher_cur.compute(
                        val['base'] *
                        tax['ref_base_sign'],
                        company_currency) * payment_ratio
                    val['tax_amount'] = voucher_cur.compute(
                        val['amount'] *
                        tax['ref_tax_sign'],
                        company_currency) * payment_ratio
                    val['account_id'] = (tax['account_paid_id'] or
                                         line.account_id.id)
                    val['account_analytic_id'] = \
                        tax['account_analytic_paid_id']

                if not val.get('account_analytic_id', False) and \
                        line.account_analytic_id and \
                        val['account_id'] == line.account_id.id:
                    val['account_analytic_id'] = line.account_analytic_id.id

                key = (val['tax_code_id'],
                       val['base_code_id'],
                       val['account_id'])

                if not (key in tax_gp):
                    tax_gp[key] = val
                else:
                    tax_gp[key]['amount'] += val['amount']
                    tax_gp[key]['base'] += val['base']
                    tax_gp[key]['base_amount'] += val['base_amount']
                    tax_gp[key]['tax_amount'] += val['tax_amount']
                    tax_gp[key]['tax_currency_gain'] += \
                        val['tax_currency_gain']

                # Second: Do the Dr: with Suspend Account
                if voucher.type in ('receipt', 'payment'):
                    vals['base_code_id'] = tax['base_code_id']
                    vals['tax_code_id'] = tax['tax_code_id']
                    vals['base_amount'] = -voucher_cur.compute(
                        val['base'] *
                        tax['base_sign'],
                        company_currency) * payment_ratio
                    vals['tax_amount'] = -voucher_cur.compute(
                        val['amount'] *
                        tax['tax_sign'],
                        company_currency) * payment_ratio
                    # USE SUSPEND ACCOUNT HERE
                    vals['account_id'] = \
                        (tax1.refer_tax_id.account_collected_id.id or
                         line.account_id.id)
                    vals['account_analytic_id'] = \
                        tax['account_analytic_collected_id']
                else:
                    vals['base_code_id'] = tax['ref_base_code_id']
                    vals['tax_code_id'] = tax['ref_tax_code_id']
                    vals['base_amount'] = -voucher_cur.compute(
                        val['base'] *
                        tax['ref_base_sign'],
                        company_currency) * payment_ratio
                    vals['tax_amount'] = -voucher_cur.compute(
                        val['amount'] *
                        tax['ref_tax_sign'],
                        company_currency) * payment_ratio
                    # USE SUSPEND ACCOUNT HERE
                    vals['account_id'] = \
                        (tax1.refer_tax_id.account_paid_id.id or
                         line.account_id.id)
                    vals['account_analytic_id'] = \
                        tax['account_analytic_paid_id']

                if not vals.get('account_analytic_id') and \
                        line.account_analytic_id and \
                        vals['account_id'] == line.account_id.id:
                    vals['account_analytic_id'] = line.account_analytic_id.id

                key = (vals['invoice_id'], vals['tax_code_id'],
                       vals['base_code_id'], vals['account_id'])

                if not (key in tax_gp):
                    tax_gp[key] = vals
                else:
                    tax_gp[key]['amount'] += vals['amount']
                    tax_gp[key]['base'] += vals['base']
                    tax_gp[key]['base_amount'] += vals['base_amount']
                    tax_gp[key]['tax_amount'] += vals['tax_amount']
                    tax_gp[key]['tax_currency_gain'] += \
                        vals['tax_currency_gain']
                    # ------------------------------------------------
        return tax_gp

    @api.model
    def _compute_tax_grouped(self, voucher, voucher_line,
                             voucher_cur, line_sign):
        invoice = voucher_line.move_line_id.invoice
        journal = voucher_line.voucher_id.journal_id
        payment_ratio = (voucher_line.amount_original and
                         (voucher_line.amount /
                          (voucher_line.amount_original or 1)) or
                         0.0)
        date = invoice.date_invoice or fields.Date.context_today(invoice)
        invoice_cur = invoice.currency_id.with_context(date=date)
        company_currency = invoice.company_id.currency_id
        # Retrieve Additional Discount, Advance and Deposit in percent.
        for line in voucher_line.move_line_id.invoice.invoice_line:
            # Each invoice line, calculate tax
            revised_price = line.price_unit * (1 - (line.discount / 100.0))
            taxes = line.invoice_line_tax_id.compute_all(
                revised_price,
                line.quantity,
                line.product_id,
                invoice.partner_id)['taxes']
            tax_gp = self._compute_one_tax_grouped(
                taxes, voucher, voucher_cur, invoice,
                invoice_cur, company_currency,
                journal, line_sign, payment_ratio,
                line, revised_price)

        return tax_gp

    @api.model
    def compute(self, voucher):
        tax_gp = {}
        date = voucher.date or fields.Date.context_today(voucher)
        voucher_cur = voucher.currency_id.with_context(date=date)
        for voucher_line in voucher.line_ids:
            line_sign = 1
            if voucher.type in ('sale', 'receipt'):
                line_sign = voucher_line.type == 'cr' and 1 or -1
            elif voucher.type in ('purchase', 'payment'):
                line_sign = voucher_line.type == 'dr' and 1 or -1
            # Each voucher line is equal to an invoice,
            # we will need to go through all of them.
            if voucher_line.move_line_id.invoice:
                tax_gp = self._compute_tax_grouped(voucher, voucher_line,
                                                   voucher_cur, line_sign)

        # rounding
        for t in tax_gp.values():
            t['base'] = voucher_cur.round(t['base'])
            t['amount'] = voucher_cur.round(t['amount'])
            t['base_amount'] = voucher_cur.round(t['base_amount'])
            t['tax_amount'] = voucher_cur.round(t['tax_amount'])
            t['tax_currency_gain'] = voucher_cur.round(t['tax_currency_gain'])

        return tax_gp

    @api.model
    def move_line_get(self, voucher_id):
        res = []
        self._cr.execute("""
            SELECT * FROM account_voucher_tax
            WHERE voucher_id=%s""", (voucher_id,))
        for t in self._cr.dictfetchall():
            if not t['amount']:
                continue
            res.append({
                'type': 'tax',
                'name': t['name'],
                'price_unit': t['amount'],
                'quantity': 1,
                'price': t['amount'] or 0.0,
                'tax_currency_gain': t['tax_currency_gain'] or 0.0,
                'account_id': t['account_id'],
                'tax_code_id': t['tax_code_id'],
                'tax_amount': t['tax_amount'],
                'account_analytic_id': t['account_analytic_id'],
            })
        return res

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
