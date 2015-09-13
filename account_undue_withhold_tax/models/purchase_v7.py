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

from openerp.osv import fields, osv
import openerp.addons.decimal_precision as dp


class purchase_order(osv.osv):

    _inherit = 'purchase.order'

    def _amount_line_tax_ex(self, cr, uid, line, context=None):
        val = 0.0
        tax_obj = self.pool.get('account.tax')
        for c in tax_obj.compute_all(cr, uid, line.taxes_id, line.price_unit,
                                     line.product_qty, line.product_id,
                                     line.order_id.partner_id)['taxes']:
            if not tax_obj.browse(cr, uid, c['id']).is_wht:
                val += c.get('amount', 0.0)
        return val

    # Overwrite
    def _amount_all(self, cr, uid, ids, field_name, arg, context=None):
        cur_obj = self.pool.get('res.currency')
        res = {}
        for order in self.browse(cr, uid, ids, context=context):
            res[order.id] = {
                'amount_untaxed': 0.0,
                'amount_tax': 0.0,
                'amount_total': 0.0,
            }
            val = val1 = 0.0
            cur = order.pricelist_id.currency_id
            for line in order.order_line:
                val1 += line.price_subtotal
                val += self._amount_line_tax_ex(cr, uid, line, context=context)
            res[order.id]['amount_tax'] = cur_obj.round(cr, uid, cur, val)
            res[order.id]['amount_untaxed'] = cur_obj.round(cr, uid, cur, val1)
            res[order.id]['amount_total'] = (res[order.id]['amount_untaxed'] +
                                             res[order.id]['amount_tax'])
        return res

    # Overwrite
    def _get_order(self, cr, uid, ids, context=None):
        result = {}
        purchase_obj = self.pool.get('purchase.order.line')
        for line in purchase_obj.browse(cr, uid, ids, context):
            result[line.order_id.id] = True
        return result.keys()

    # Overwrite
    _columns = {
        'amount_untaxed': fields.function(
            _amount_all,
            string='Untaxed Amount',
            digits_compute=dp.get_precision('Account'),
            store={
                'purchase.order.line': (_get_order, None, 10),
            }, multi="sums",
            help="The amount without tax"),
        'amount_tax': fields.function(
            _amount_all,
            string='Taxes',
            digits_compute=dp.get_precision('Account'),
            store={
                'purchase.order.line': (_get_order, None, 10),
            }, multi="sums", help="The tax amount"),
        'amount_total': fields.function(
            _amount_all,
            string='Total',
            digits_compute=dp.get_precision('Account'),
            store={
                'purchase.order.line': (_get_order, None, 10),
            }, multi="sums", help="The total amount"),
        'amount_untaxed': fields.function(
            _amount_all,
            string='Untaxed Amount',
            digits_compute=dp.get_precision('Account'),
            store={
                'purchase.order.line': (_get_order, None, 10),
            }, multi="sums",
            help="The amount without tax",
            track_visibility='always'),
        'amount_tax': fields.function(
            _amount_all,
            string='Taxes',
            digits_compute=dp.get_precision('Account'),
            store={
                'purchase.order.line': (_get_order, None, 10),
            }, multi="sums", help="The tax amount"),
        'amount_total': fields.function(
            _amount_all,
            string='Total',
            digits_compute=dp.get_precision('Account'),
            store={
                'purchase.order.line': (_get_order, None, 10),
            }, multi="sums",
            help="The total amount"),
    }

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
