# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from lxml import etree
from openerp import api, fields, models, _
from openerp.osv.orm import setup_modifiers
from openerp.exceptions import except_orm, Warning, RedirectWarning


class CrossoveredBudget(models.Model):
    _inherit = 'crossovered.budget'

    @api.multi
    def budget_validate(self):
        self.crossovered_budget_line.create_analytic_account_activity()
        return super(CrossoveredBudget, self).budget_validate()


class CrossoveredBudgetLines(models.Model):
    _inherit = 'crossovered.budget.lines'

    activity_group_id = fields.Many2one(
        'account.activity.group',
        string='Activity Group',
        required=True,
    )
    activity_id = fields.Many2one(
        'account.activity',
        string='Activity',
        required=False,
    )

    @api.onchange('activity_id')
    def onchange_activity_id(self):
        self.activity_group_id = self.activity_id.activity_group_id
        # Set Analytic and Account
        Analytic = self.env['account.analytic.account']
        analytic = Analytic.get_matched_analytic(self)
        self.account_analytic_id = analytic

    @api.multi
    def create_analytic_account_activity(self):
        """ Create analytic account for those not been created """
        Analytic = self.env['account.analytic.account']
        for line in self:
            if line.activity_id:
                line.analytic_account_id = \
                    Analytic.create_matched_analytic(line)
        return

