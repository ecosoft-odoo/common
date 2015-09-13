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

from openerp import models, fields, api, _
import openerp.addons.decimal_precision as dp
from openerp.exceptions import except_orm


class account_invoice(models.Model):

    _inherit = 'account.invoice'

    amount_retention = fields.Float(
        string='Retention',
        digits=dp.get_precision('Account'),
        readonly=False)
    retention_on_payment = fields.Boolean(
        string='Retention on Payment',
        compute='_retention_on_payment',
        store=True,
        help="If checked, retention will done during payment")

    @api.one
    @api.depends('invoice_line.price_subtotal',
                 'tax_line.amount',
                 'amount_retention')
    def _compute_amount(self):
        super(account_invoice, self)._compute_amount()
        self.amount_tax = sum(line.amount
                              for line in self.tax_line
                              if not line.is_wht)  # WHT
        amount_total = self.amount_untaxed + self.amount_tax
        if not self.retention_on_payment:
            self.amount_total = amount_total - self.amount_retention  # RET
        else:
            self.amount_total = amount_total

    @api.one
    @api.depends('partner_id')
    def _retention_on_payment(self):
        self.retention_on_payment = \
            self.partner_id.property_retention_on_payment

    @api.multi
    def invoice_pay_customer(self):
        res = super(account_invoice, self).invoice_pay_customer()
        if res:
            res['context']['default_amount'] = 0.0
        return res


class account_invoice_line(models.Model):

    _inherit = "account.invoice.line"

    @api.model
    def move_line_get(self, invoice_id):

        res = super(account_invoice_line, self).move_line_get(invoice_id)
        inv = self.env['account.invoice'].browse(invoice_id)

        if inv.amount_retention > 0.0 and not inv.retention_on_payment:
            sign = -1
            # sign = inv.type in ('out_invoice','in_invoice') and -1 or 1
            # account code for advance
            prop = inv.type in ('out_invoice', 'out_refund') \
                and self.env['ir.property'].get(
                    'property_account_retention_customer',
                    'res.partner') \
                or self.env['ir.property'].get(
                    'property_account_retention_supplier',
                    'res.partner')
            if not prop:
                raise except_orm(
                    _('Error!'),
                    _('No retention account defined in the system!'))
            account = self.env['account.fiscal.position'].map_account(prop)
            res.append({
                'type': 'src',
                'name': _('Retention Amount'),
                'price_unit': sign * inv.amount_retention,
                'quantity': 1,
                'price': sign * inv.amount_retention,
                'account_id': account.id,
                'product_id': False,
                'uos_id': False,
                'account_analytic_id': False,
                'taxes': False,
            })
        return res


class account_invoice_tax(models.Model):

    _inherit = 'account.invoice.tax'

    is_wht = fields.Boolean(
        string="Withholding Tax",
        readonly=True,
        default=False,
        help="Tax will be withhold and will be used in Payment")

    @api.model
    def compute(self, invoice):
        """ Call Super but by pass everything (overwrite) """
        # Call Super but ignore the result
        super(account_invoice_tax, self).compute(invoice)

        tax_grouped = {}
        tax_obj = self.env['account.tax']
        currency = invoice.currency_id.with_context(
            date=invoice.date_invoice or
            fields.Date.context_today(invoice))
        company_currency = invoice.company_id.currency_id
        for line in invoice.invoice_line:
            revised_price = (
                line.price_unit * (1 - (line.discount or 0.0) / 100.0))
            taxes = line.invoice_line_tax_id.compute_all(
                revised_price,
                line.quantity, line.product_id, invoice.partner_id)['taxes']
            for tax in taxes:
                # ecosoft: undue vat
                tax1 = self.env['account.tax'].browse(tax['id'])
                use_suspend_acct = tax1.is_suspend_tax
                # -- ecosoft
                val = {
                    'invoice_id': invoice.id,
                    'name': tax['name'],
                    'amount': tax['amount'],
                    'manual': False,
                    'sequence': tax['sequence'],
                    'base': currency.round(tax['price_unit'] *
                                           line['quantity']),
                    'is_wht': tax_obj.browse(tax['id']).is_wht  # ecosoft
                }
                # ecosoft: undue vat
                if val['is_wht']:
                    # Check Threshold first (with document's currency)
                    base = currency.compute((revised_price * line.quantity),
                                            company_currency, round=False)
                    if abs(base) and (abs(base) <
                                      tax_obj.browse(tax['id']).threshold_wht):
                        continue
                # -- ecosoft
                if invoice.type in ('out_invoice', 'in_invoice'):
                    val['base_code_id'] = tax['base_code_id']
                    val['tax_code_id'] = tax['tax_code_id']
                    val['base_amount'] = currency.compute(
                        val['base'] * tax['base_sign'],
                        company_currency,
                        round=False)
                    val['tax_amount'] = currency.compute(
                        val['amount'] * tax['tax_sign'],
                        company_currency,
                        round=False)
                    val['account_id'] = (use_suspend_acct and
                                         tax['account_suspend_collected_id'] or
                                         tax['account_collected_id'] or
                                         line.account_id.id)
                    val['account_analytic_id'] = \
                        tax['account_analytic_collected_id']
                else:
                    val['base_code_id'] = tax['ref_base_code_id']
                    val['tax_code_id'] = tax['ref_tax_code_id']
                    val['base_amount'] = currency.compute(
                        val['base'] * tax['ref_base_sign'],
                        company_currency,
                        round=False)
                    val['tax_amount'] = currency.compute(
                        val['amount'] * tax['ref_tax_sign'],
                        company_currency,
                        round=False)
                    val['account_id'] = (use_suspend_acct and
                                         tax['account_suspend_paid_id'] or
                                         tax['account_collected_id'] or
                                         line.account_id.id)
                    val['account_analytic_id'] = \
                        tax['account_analytic_paid_id']

                # If the taxes generate moves on the same financial
                # account as the invoice line
                # and no default analytic account is defined at
                # the tax level, propagate the
                # analytic account from the invoice line to the tax line.
                # This is necessary
                # in situations were (part of) the taxes cannot be reclaimed,
                # to ensure the tax move is allocated to the proper
                # analytic account.
                if not val.get('account_analytic_id') and \
                        line.account_analytic_id and \
                        val['account_id'] == line.account_id.id:
                    val['account_analytic_id'] = line.account_analytic_id.id

                key = (val['tax_code_id'],
                       val['base_code_id'],
                       val['account_id'])
                if key not in tax_grouped:
                    tax_grouped[key] = val
                else:
                    tax_grouped[key]['amount'] += val['amount']
                    tax_grouped[key]['base'] += val['base']
                    tax_grouped[key]['base_amount'] += val['base_amount']
                    tax_grouped[key]['tax_amount'] += val['tax_amount']
                    tax_grouped[key]['is_wht'] = val['is_wht']   # ecosoft

        for t in tax_grouped.values():
            t['base'] = currency.round(t['base'])
            t['amount'] = currency.round(t['amount'])
            t['base_amount'] = currency.round(t['base_amount'])
            t['tax_amount'] = currency.round(t['tax_amount'])
        return tax_grouped

    @api.model
    def move_line_get(self, invoice_id):
        res = []
        self._cr.execute(
            """SELECT * FROM account_invoice_tax WHERE is_wht=False
                and invoice_id = %s""",  # Added is_wht=False
            (invoice_id,)
        )
        for row in self._cr.dictfetchall():
            if not (row['amount'] or row['tax_code_id'] or row['tax_amount']):
                continue
            res.append({
                'type': 'tax',
                'name': row['name'],
                'price_unit': row['amount'],
                'quantity': 1,
                'price': row['amount'] or 0.0,
                'account_id': row['account_id'],
                'tax_code_id': row['tax_code_id'],
                'tax_amount': row['tax_amount'],
                'account_analytic_id': row['account_analytic_id'],
            })
        return res

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
