# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
from openerp import api, fields, models, _
from openerp.exceptions import except_orm, Warning, RedirectWarning


class AccountActivityGroup(models.Model):
    _name = 'account.activity.group'
    _description = 'Activity Group'

    name = fields.Char(
        string='Activity Group',
        required=True,
    )
    activity_ids = fields.One2many(
        'account.activity',
        'activity_group_id',
        string='Activities',
    )
    _sql_constraints = [
        ('activity_uniq', 'unique(name)',
         'Activity Group must be unique!'),
    ]


class AccountActivity(models.Model):
    _name = 'account.activity'
    _description = 'Activity'

    activity_group_id = fields.Many2one(
        'account.activity.group',
        string='Activity Group',
    )
    name = fields.Char(
        string='Activity',
        required=True,
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
    )
    _sql_constraints = [
        ('activity_uniq', 'unique(name, group_id)',
         'Activity must be unique per group!'),
    ]

    @api.multi
    def name_get(self):
        result = []
        for activity in self:
            result.append(
                (activity.id,
                 "%s / %s" % (activity.activity_group_id.name or '-',
                              activity.name or '-')))
        return result
