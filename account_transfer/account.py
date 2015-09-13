# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#     Copyright (C) 2012 Cubic ERP - Teradata SAC (<http://cubicerp.com>).
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

from openerp.osv import fields, osv


class account_journal(osv.osv):

    _name = 'account.journal'
    _inherit = 'account.journal'

    _columns = {
        'have_partner': fields.boolean('Require Partner'),
        'account_transit': fields.many2one(
            'account.account', 'Account Transit',
            help="""Account used to make money transfers
                    between bank and cash journals"""),
    }
    _defaults = {
        'have_partner': False,
    }

account_journal()


class account_voucher(osv.osv):

    _name = 'account.voucher'
    _inherit = 'account.voucher'

    _columns = {
        'transfer_id': fields.many2one(
            'account.transfer',
            'Money Transfer',
            readonly=True,
            states={'draft': [('readonly', False)]}),
        'type': fields.selection(
            [('sale', 'Sale'),
             ('purchase', 'Purchase'),
             ('payment', 'Payment'),
             ('receipt', 'Receipt'),
             ('transfer', 'Transfer')],
            'Default Type',
            readonly=True,
            states={'draft': [('readonly', False)]}),
    }
    _document_type = {
        'sale': 'Sales Receipt',
        'purchase': 'Purchase Receipt',
        'payment': 'Supplier Payment',
        'receipt': 'Customer Payment',
        'transfer': 'Money Transfer',
        False: 'Payment',
    }

    def first_move_line_get(
            self, cr, uid, voucher_id, move_id,
            company_currency, current_currency, context=None):
        if context is None:
            context = {}
        res = super(account_voucher, self).first_move_line_get(
            cr, uid, voucher_id, move_id, company_currency, current_currency,
            context=context)
        voucher = self.pool.get('account.voucher').browse(
            cr, uid, voucher_id, context)
        if voucher.type == 'transfer':
            # import pdb; pdb.set_trace()
            if voucher.transfer_id.src_journal_id.id == voucher.journal_id.id:
                res['credit'] = voucher.paid_amount_in_company_currency
            else:
                res['debit'] = voucher.paid_amount_in_company_currency
            if res['debit'] < 0:
                res['credit'] = -res['debit']
                res['debit'] = 0.0
            if res['credit'] < 0:
                res['debit'] = -res['credit']
                res['credit'] = 0.0
            sign = res['debit'] - res['credit'] < 0 and -1 or 1
            res['currency_id'] = company_currency != current_currency and \
                current_currency or False
            res['amount_currency'] = company_currency != current_currency and \
                sign * voucher.amount or 0.0
        return res

account_voucher()
