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

from openerp import models, fields, api


class account_tax(models.Model):

    _inherit = 'account.tax'

    account_suspend_collected_id = fields.Many2one(
        'account.account',
        string='Invoice Suspend Tax Account',
        help="""For selected product/service, this account will be used during
                invoicing as suspend account of Invoice Tax Account""")
    account_suspend_paid_id = fields.Many2one(
        'account.account',
        string='Refund Suspend Tax Account',
        help="""For selected product/service, this account will be used during
                invoicing as suspend account of Refund Tax Account""")
    is_suspend_tax = fields.Boolean(
        string='Suspend Tax',
        default=False,
        help="""This is a suspended tax account.
                The tax point will be deferred to the time of payment""")
    is_wht = fields.Boolean(
        string='Withholding Tax',
        help="Tax will be withhold and will be used in Payment")
    threshold_wht = fields.Float(
        string='Threshold Amount',
        help="""Withholding Tax will be applied only if base amount more
                or equal to threshold amount""")
    refer_tax_id = fields.Many2one(
        'account.tax',
        string='Refer Tax',
        help="Which Tax this Suspend Tax is referring to")

    @api.model
    def _unit_compute(self, taxes, price_unit,
                      product=None, partner=None, quantity=0):
        res = super(account_tax, self)._unit_compute(taxes,
                                                     price_unit,
                                                     product=product,
                                                     partner=partner,
                                                     quantity=quantity)
        for r in res:
            tax = self.browse(r['id'])
            account_suspend_collected_id = tax.account_suspend_collected_id.id
            account_suspend_paid_id = tax.account_suspend_paid_id.id
            r.update({
                'account_suspend_collected_id': account_suspend_collected_id,
                'account_suspend_paid_id': account_suspend_paid_id,
            })
        return res

    @api.model
    def _unit_compute_inv(self, taxes, price_unit,
                          product=None, partner=None):
        res = super(account_tax, self)._unit_compute_inv(taxes,
                                                         price_unit,
                                                         product=product,
                                                         partner=partner)
        for r in res:
            tax = self.browse(r['id'])
            account_suspend_collected_id = tax.account_suspend_collected_id.id
            account_suspend_paid_id = tax.account_suspend_paid_id.id
            r.update({
                'account_suspend_collected_id': account_suspend_collected_id,
                'account_suspend_paid_id': account_suspend_paid_id,
            })
        return res

    @api.one
    @api.depends('is_wht')
    def onchange_is_wht(self):
        self.is_suspend_tax = False

    @api.one
    @api.depends('is_suspend_tax')
    def onchange_is_suspend_tax(self, is_suspend_tax):
        self.is_wht = False

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
