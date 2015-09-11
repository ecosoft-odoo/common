# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
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
##############################################################################

from lxml import etree
import time

from openerp import models, fields, api, _
from openerp.exceptions import except_orm
import openerp.addons.decimal_precision as dp


class AccountBilling(models.Model):

    # Private attributes
    _name = 'account.billing'
    _description = 'Account Billing'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    # Fields declaration
    number = fields.Char(
        string='Number',
        size=32,
        readonly=True,
        copy=False,)
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        change_default=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: self._context.get('partner_id', False))
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: self._default_journal())
    currency_id = fields.Many2one(
        'res.currency',
        related='journal_id.currency',
        string='Currency')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self:
            self.env['res.company']._company_default_get('account.billing'))
    date = fields.Date(
        string='Date',
        select=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: time.strftime('%Y-%m-%d'),
        help="Effective date for accounting entries")
    line_cr_ids = fields.One2many(
        'account.billing.line',
        'billing_id',
        string='Credits',
        context={'default_type': 'cr'},
        readonly=True,
        states={'draft': [('readonly', False)]},
        copy=False)
    period_id = fields.Many2one(
        'account.period',
        string='Period',
        default=lambda self: self._default_period(),
        required=True, readonly=True,
        states={'draft': [('readonly', False)]})
    narration = fields.Text(
        string='Notes',
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: self._context.get('narration', False))
    state = fields.Selection(
        [('draft', 'Draft'),
         ('cancel', 'Cancelled'),
         ('billed', 'Billed')],
        string='Status',
        readonly=True,
        default='draft',
        help="""* The 'Draft' status is used when a user is encoding a new and
            unconfirmed billing.
            \n* The 'Billed' status is used when user create billing,
            a billing number is generated
            \n* The 'Cancelled' status is used when user cancel billing.""")
    reference = fields.Char(
        string='Ref #',
        size=64,
        readonly=True,
        states={'draft': [('readonly', False)]},
        help="Transaction reference number.",
        default=lambda self: self._context.get('reference', False),
        copy=False)
    billing_amount = fields.Float(
        string='Billing Amount',
        compute='_compute_billing_amount',
        readonly=True,
        store=True,
        help="""Computed as the difference between the amount stated in the
            billing and the sum of allocation on the billing lines.""")
    payment_id = fields.Many2one(
        'account.voucher',
        string='Payment Ref#',
        required=False,
        readonly=True)
    name = fields.Char(
       string='Memo',
       size=256,
       readonly=True,
       states={'draft': [('readonly', False)]})

    @api.model
    def _default_journal(self):
        return self.env['account.journal'].search([('type', '=', 'bank')],
                                                  limit=1)

    @api.model
    def _default_period(self):
        return self.env['account.period'].find()

    @api.multi
    def name_get(self):
        result = []
        for billing in self:
            result.append((billing.id, (billing.numbe or 'N/A')))
        return result

    @api.v7
    def fields_view_get(self, cr, uid, view_id=None, view_type=False,
                        context=None, toolbar=False, submenu=False):
        mod_obj = self.pool.get('ir.model.data')
        if context is None:
            context = {}
        if view_type == 'form':
            if not view_id and context.get('invoice_type'):
                if context.get('invoice_type') in \
                        ('out_invoice', 'out_refund'):
                    result = mod_obj.get_object_reference(
                        cr, uid,
                        'account_billing',
                        'view_vendor_receipt_form')
                else:
                    result = mod_obj.get_object_reference(
                        cr, uid, 'account_billing', 'view_vendor_payment_form')
                result = result and result[1] or False
                view_id = result
            if not view_id and context.get('line_type'):
                if context.get('line_type') == 'customer':
                    result = mod_obj.get_object_reference(
                        cr, uid, 'account_billing', 'view_vendor_receipt_form')
                else:
                    result = mod_obj.get_object_reference(
                        cr, uid, 'account_billing', 'view_vendor_payment_form')
                result = result and result[1] or False
                view_id = result
        res = super(AccountBilling, self).fields_view_get(
            cr, uid, view_id=view_id, view_type=view_type, context=context,
            toolbar=toolbar, submenu=submenu)
        doc = etree.XML(res['arch'])
        if context.get('type', 'sale') in ('purchase', 'payment'):
            nodes = doc.xpath("//field[@name='partner_id']")
            for node in nodes:
                node.set('domain', "[('supplier', '=', True)]")
        res['arch'] = etree.tostring(doc)
        return res

    @api.one
    @api.depends('line_cr_ids')
    def _compute_billing_amount(self):
        credit = 0.0
        for l in self.line_cr_ids:
            credit += l.amount
        currency = self.currency_id or self.company_id.currency_id
        self.billing_amount = currency.round(credit)

    @api.model
    def create(self, vals):
        billing = super(AccountBilling, self).create(vals)
        billing.create_send_note()
        return billing

    @api.v7
    def onchange_partner_id(self, cr, uid, ids, partner_id, journal_id,
                            currency_id, date, context=None):
        if context is None:
            context = {}
        ctx = context.copy()
        ctx.update({'billing_date_condition': ['|',
                                               ('date_maturity', '=', False),
                                               ('date_maturity', '<=', date)]})
        if not journal_id:
            return {}
        res = self.recompute_billing_lines(cr, uid, ids,
                                           partner_id, journal_id,
                                           currency_id, date, context=ctx)
        return res

    @api.v7
    def recompute_billing_lines(self, cr, uid, ids,
                                partner_id, journal_id,
                                currency_id, date, context=None):

        def _remove_noise_in_o2m():
            if line.reconcile_partial_id:
                sign = 1
                if currency_id == line.currency_id.id:
                    if line.amount_residual_currency * sign <= 0:
                        return True
                else:
                    if line.amount_residual * sign <= 0:
                        return True
            return False

        if context is None:
            context = {}
        billing_date_condition = context.get('billing_date_condition', [])
        context_multi_currency = context.copy()
        if date:
            context_multi_currency.update({'date': date})

        currency_pool = self.pool.get('res.currency')
        move_line_pool = self.pool.get('account.move.line')
        journal_pool = self.pool.get('account.journal')
        line_pool = self.pool.get('account.billing.line')
        default = {'value': {'line_cr_ids': []}}
        line_cr_ids = ids and \
            line_pool.search(cr, uid, [('billing_id', '=', ids[0])]) or \
            False
        if line_cr_ids:
            line_pool.unlink(cr, uid, line_cr_ids)

        if not partner_id or not journal_id:
            return default

        journal = journal_pool.browse(cr, uid, journal_id, context=context)
        currency_id = currency_id or journal.company_id.currency_id.id

#         if journal.type not in ('cash', 'bank'):
#             return default

        total_credit = price = 0.0
        account_type = 'receivable'

        if not context.get('move_line_ids', False):
            ids = move_line_pool.search(cr, uid, [
                ('state', '=', 'valid'),
                ('account_id.type', '=', account_type),
                ('reconcile_id', '=', False),
                ('partner_id', '=', partner_id),
                ('journal_id', '=', journal_id),
            ] + billing_date_condition, context=context)
        else:
            ids = context['move_line_ids']
        invoice_id = context.get('invoice_id', False)
        company_currency = journal.company_id.currency_id.id
        move_line_found = False

        # Order the lines by most old first
        ids.reverse()
        account_move_lines = move_line_pool.browse(cr, uid, ids,
                                                   context=context)

        # Compute total debit/credit and find matching open amount or invoice
        for line in account_move_lines:
            if _remove_noise_in_o2m():
                continue

            if invoice_id:
                if line.invoice.id == invoice_id:
                    # If the invoice linked to the billing line is
                    # equal to the invoice_id in context
                    # then we assign the amount on that line,
                    # whatever the other billing lines
                    move_line_found = line.id
                    break
            elif currency_id == company_currency:
                # Otherwise treatments is the same but with other field names
                if line.amount_residual == price:
                    # If the amount residual is equal the amount billing,
                    # we assign it to that billing
                    # line, whatever the other billing lines
                    move_line_found = line.id
                    break
                # Otherwise, split billing amount on each line (oldest first)
                total_credit += line.credit or 0.0
            elif currency_id == line.currency_id.id:
                if line.amount_residual_currency == price:
                    move_line_found = line.id
                    break
                total_credit += line.credit and line.amount_currency or 0.0

        # Billing line creation
        for line in account_move_lines:

            if _remove_noise_in_o2m():
                continue

            if line.currency_id and currency_id == line.currency_id.id:
                amount_original = abs(line.amount_currency)
                amount_unreconciled = abs(line.amount_residual_currency)
            else:
                amount_original = currency_pool.compute(
                                                    cr, uid,
                                                    company_currency,
                                                    currency_id,
                                                    line.credit or 0.0)
                amount_unreconciled = currency_pool.compute(
                                                    cr, uid,
                                                    company_currency,
                                                    currency_id,
                                                    abs(line.amount_residual))
            line_currency_id = line.currency_id and \
                line.currency_id.id or \
                company_currency
            amount = move_line_found == line.id and \
                min(abs(price), amount_unreconciled) or \
                amount_unreconciled
            rs = {
                'move_line_id': line.id,
                'type': line.credit and 'dr' or 'cr',
                'reference': line.invoice.reference,
                'amount_original': amount_original,
                'amount': amount,
                'date_original': line.date,
                'date_due': line.date_maturity,
                'amount_unreconciled': amount_unreconciled,
                'currency_id': line_currency_id,
            }
            # Negate DR records
            if rs['type'] == 'dr':
                rs['amount_original'] = - rs['amount_original']
                rs['amount'] = - rs['amount']
                rs['amount_unreconciled'] = - rs['amount_unreconciled']
            if rs['amount_unreconciled'] == rs['amount']:
                rs['reconcile'] = True
            else:
                rs['reconcile'] = False
            default['value']['line_cr_ids'].append(rs)
        line_cr_ids = default['value']['line_cr_ids']
        billing_amount = sum([line['amount'] for line in line_cr_ids])
        default['value']['billing_amount'] = billing_amount
        return default

    @api.v7
    def onchange_date(self, cr, uid, ids, date,
                      currency_id, company_id, context=None):
        if context is None:
            context = {}
        res = {'value': {}}
        # Set the period of the billing
        period_pool = self.pool.get('account.period')
        ctx = context.copy()
        pids = period_pool.find(cr, uid, date, context)
        if pids:
            res['value'].update({'period_id': pids[0]})
        res2 = self.onchange_partner_id(cr, uid, ids,
                                        ctx.get('partner_id', False),
                                        ctx.get('journal_id', False),
                                        currency_id, date, context)
        for key in res2.keys():
            res[key].update(res2[key])
        return res

    def onchange_journal(self, cr, uid, ids, journal_id, partner_id,
                         date, company_id, context=None):
        if not journal_id:
            return False
        journal_pool = self.pool.get('account.journal')
        journal = journal_pool.browse(cr, uid, journal_id, context=context)
        vals = {'value': {}}
        currency_id = False
        if journal.currency:
            currency_id = journal.currency.id
        vals['value'].update({'currency_id': currency_id})
        res = self.onchange_partner_id(cr, uid, ids,
                                       partner_id, journal_id,
                                       currency_id, date, context)
        for key in res.keys():
            vals[key].update(res[key])
        return vals

    @api.multi
    def validate_billing(self):
        self.write({'state': 'billed'})
        self.write({'number': self.env['ir.sequence'].get('account.billing')})
        self.message_post(body=_('Billing is billed.'))

    @api.multi
    def action_cancel_draft(self):
        self.write({'state': 'draft'})
        self.delete_workflow()
        self.create_workflow()
        self.message_post(body=_('Billing is reset to draft'))
        return True

    @api.multi
    def cancel_billing(self):
        self.write({'state': 'cancel'})
        self.message_post(body=_('Billing is cancelled'))
        return True

    @api.multi
    def unlink(self):
        for billing in self:
            if billing.state not in ('draft', 'cancel'):
                raise except_orm(
                     _('Invalid Action!'),
                     _('Cannot delete billing(s) which are already billed.'))
        return super(AccountBilling, self).unlink()

    _document_type = {
        'payment': 'Supplier Billing',
        'receipt': 'Customer Billing',
        False: 'Payment',
    }

    @api.multi
    def create_send_note(self):
        message = "Billing Document <b>created</b>."
        self.message_post(body=message,
                          subtype="account_billing.mt_billing")


class AccountBillingLine(models.Model):

    _name = 'account.billing.line'
    _description = 'Billing Lines'
    _order = 'move_line_id'

    billing_id = fields.Many2one(
        'account.billing',
        string='billing',
        required=1,
        ondelete='cascade')
    name = fields.Char(
        string='Description',
        size=256)
    reference = fields.Char(
        string='Invoice Reference',
        size=64,
        help="The partner reference of this invoice.")
    partner_id = fields.Many2one(
        'res.partner',
        related='billing_id.partner_id',
        string='Partner')
    untax_amount = fields.Float(string='Untaxed Amount')
    amount = fields.Float(
        string='Amount',
        digits_compute=dp.get_precision('Account'))
    reconcile = fields.Boolean(string='Full Reconcile')
    type = fields.Selection(
        [('dr', 'Debit'),
         ('cr', 'Credit')],
        string='Dr/Cr')
    account_analytic_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account')
    move_line_id = fields.Many2one(
        'account.move.line',
        string='Journal Item')
    date_original = fields.Date(
        related='move_line_id.date',
        string='Date',
        readonly=1)
    date_due = fields.Date(
        related='move_line_id.date_maturity',
        string='Due Date',
        readonly=1)
    amount_original = fields.Float(
        string='Original Amount',
        compute='_compute_balance',
        digits_compute=dp.get_precision('Account'),
        store=True)
    amount_unreconciled = fields.Float(
        string='Open Balance',
        comput='_compute_balance',
        digits_compute=dp.get_precision('Account'),
        store=True)

    @api.one
    def _compute_balance(self):
        company_currency = self.billing_id.journal_id.company_id.currency_id.id
        billing_currency = self.billing_id.currency_id and \
            self.billing_id.currency_id.id or \
            company_currency
        move_line = self.move_line_id or False
        currency_pool = self.env['res.currency'].with_context(
                                                    date=self.billing_id.date)
        # Default from - to currency
        from_cur = move_line.currency_id.id
        to_cur = billing_currency
        if not move_line:
            self.amount_original = 0.0
            self.amount_unreconciled = 0.0
        elif move_line.currency_id and \
                billing_currency == move_line.currency_id.id:
            self.amount_original = currency_pool.compute(
                                    from_cur, to_cur,
                                    abs(move_line.amount_currency))
            self.amount_unreconciled = currency_pool.compute(
                                    from_cur or company_currency, to_cur,
                                    abs(move_line.amount_residual_currency))
        elif move_line and move_line.credit > 0:
            self.amount_original = currency_pool.compute(
                                    company_currency, billing_currency,
                                    move_line.credit)
            self.amount_unreconciled = currency_pool.compute(
                                        company_currency, billing_currency,
                                        abs(move_line.amount_residual))
        else:
            self.amount_original = currency_pool.compute(
                                    company_currency, billing_currency,
                                    move_line.debit)
            self.amount_unreconciled = currency_pool.compute(
                                        company_currency, billing_currency,
                                        abs(move_line.amount_residual))

    @api.v7
    def onchange_reconcile(self, cr, uid, ids,
                           reconcile, amount,
                           amount_unreconciled, context=None):
        vals = {'amount': 0.0}
        if reconcile:
            vals = {'amount': amount_unreconciled}
        return {'value': vals}

    @api.v7
    def onchange_amount(self, cr, uid, ids,
                        reconcile, amount,
                        amount_unreconciled, context=None):
        vals = {}
        if amount == amount_unreconciled:
            vals = {'reconcile': True}
        else:
            vals = {'reconcile': False, 'amount': 0.0}
        return {'value': vals}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
