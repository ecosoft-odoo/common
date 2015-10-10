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

from openerp.osv import fields, osv


class res_partner(osv.osv):
    _inherit = 'res.partner'
    """
    TBD: We are using this partner_v7, because can't find way to make property field in v8.
    """
    _columns = {
        'property_account_deposit_customer': fields.property(
            type='many2one',
            relation='account.account',
            string="Account Advance Customer",
            view_load=True,
            domain="[('type', '!=', 'view')]",
            help="This account will be used instead of the default one as the advance account for the current partner",
            required=True,
            readonly=True),
    }
    
res_partner()
    
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
