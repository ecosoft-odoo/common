# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Jordi Ballester (Eficent)
#    Copyright 2015 Eficent
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
from openerp import api, models


class AccountVoucher(models.Model):
    _inherit = "account.voucher"

    @api.model
    def _finalize_voucher(self, voucher):
        return voucher

    @api.model
    def _finalize_line_total(self, voucher, line_total,
                             move_id, company_currency,
                             current_currency):
        return line_total

    @api.v7
    def action_move_line_create(self, cr, uid, ids, context=None):
        """ Add HOOK """
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

            # Create one move line per voucher line where amount is not 0.0
            line_total, rec_list_ids = self.voucher_move_line_create(
                cr, uid,
                voucher.id, line_total,
                move_id, company_currency,
                current_currency, context)
            # HOOK
            line_total = self._finalize_line_total(cr, uid,
                                                   voucher, line_total,
                                                   move_id, company_currency,
                                                   current_currency, context)
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
            # HOOK
            voucher = self._finalize_voucher(cr, uid, voucher, context)
            # --
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
