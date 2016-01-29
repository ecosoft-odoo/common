# -*- coding: utf-8 -*-
import itertools
from lxml import etree
from openerp.osv.orm import setup_modifiers
from openerp import api, fields, models, _
from openerp.exceptions import except_orm, Warning


class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    activity_group_id = fields.Many2one(
        'account.activity.group',
        string='Activity Group',
    )
    activity_id = fields.Many2one(
        'account.activity',
        string='Activity',
    )

    @api.onchange('activity_id')
    def _onchange_activity_id(self):
        self.activity_group_id = self.activity_id.activity_group_id
        self.account_id = self.activity_id.account_id
        # Set Analytic and Account
        Analytic = self.env['account.analytic.account']
        analytic = Analytic.get_matched_analytic(self)
        self.account_analytic_id = analytic

    @api.model
    def create(self, vals):
        res = super(AccountInvoiceLine, self).create(vals)
        if not vals.get('account_analytic_id', False) and \
                vals.get('activity_id', False):
            Analytic = self.env['account.analytic.account']
            res.account_analytic_id = Analytic.create_matched_analytic(res)
        return res

    @api.multi
    def write(self, vals):
        res = super(AccountInvoiceLine, self).write(vals)
        for rec in self:
            if not rec.account_analytic_id and rec.activity_id:
                Analytic = self.env['account.analytic.account']
                self.account_analytic_id = \
                    Analytic.create_matched_analytic(rec)
        return res
