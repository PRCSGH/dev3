# © 2021 onDevelop.sa
# Autor: Idelis Gé Ramírez

from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        '''Redefined for use the fixed price field in the price_unit calculation.

        If the pricelist have a line with the selected product and this lines
        is set like Fixed Price the price in the quotation use the field
        fixed_price defined in the pricelist line.

        '''
        result = super(SaleOrderLine, self).product_uom_change()

        filter_f = lambda l: (
            l.uom_id.id == self.product_uom.id and
            self.product_id.product_tmpl_id.id == l.product_tmpl_id.id and
            l.compute_price == 'fixed')
        pricelist_line = self.order_id.pricelist_id.item_ids.filtered(filter_f)
        if len(pricelist_line) == 1:
            self.price_unit = pricelist_line.fixed_price
