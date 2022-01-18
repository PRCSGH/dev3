import odoo.addons.decimal_precision as dp
from odoo import models, fields, api, _
from odoo.addons.sale_stock.models.sale_order import SaleOrderLine
from odoo.exceptions import Warning, ValidationError, UserError


class sale_order(models.Model):
	_inherit = 'sale.order'

	def action_confirm(self):
		res = super(sale_order, self).action_confirm()
		for order in self:
			if order.pricelist_id:
				for lines in order.order_line.filtered(lambda l:l.price_unit > 0.00):
					pricelist_item = order.pricelist_id.item_ids.filtered(lambda l:l.compute_price == 'fixed' and l.applied_on == '1_product' and l.uom_id.id == lines.product_uom.id)
					if pricelist_item:
						each_price = order.pricelist_id.item_ids.search([('product_tmpl_id', '=', lines.product_id.product_tmpl_id.id),
															 ('compute_price', '=', 'fixed'), ('applied_on', '=', '1_product'),
															 ('pricelist_id', '=', order.pricelist_id.id),('uom_id','=',lines.product_uom.id)])
						if not each_price:
							order.pricelist_id.write({'item_ids':[(0, 0, {'applied_on':'1_product',
												  'product_tmpl_id':lines.product_id.product_tmpl_id.id,
												  'uom_id' : lines.product_uom.id,
												  'fixed_price':lines.price_unit})]})
						else:
							each_price.fixed_price = lines.price_unit
					else:
						order.pricelist_id.write({'item_ids':[(0, 0, {'applied_on':'1_product',
												  'product_tmpl_id':lines.product_id.product_tmpl_id.id,
												  'uom_id' : lines.product_uom.id,
												  'fixed_price':lines.price_unit
												  })]})
		return res



class SaleOrderLineInherit(models.Model):
	_inherit = "sale.order.line"

	@api.onchange('product_id')
	def product_id_change(self):
		for order in self:
			if not order.product_id:
				return {'domain': {'product_uom': []}}

			vals = {}
			domain = {'product_uom': [('category_id', '=', order.product_id.uom_id.category_id.id)]}
			if not order.product_uom or (order.product_id.uom_id.id != order.product_uom.id):
				vals['product_uom'] = order.product_id.uom_id
				vals['product_uom_qty'] = 1.0

			product = order.product_id.with_context(
				lang=order.order_id.partner_id.lang,
				partner=order.order_id.partner_id.id,
				quantity=vals.get('product_uom_qty') or order.product_uom_qty,
				date=order.order_id.date_order,
				pricelist=order.order_id.pricelist_id.id,
				uom=order.product_uom.id
			)

			result = {'domain': domain}

			title = False
			message = False
			warning = {}
			if product.sale_line_warn != 'no-message':
				title = _("Warning for %s") % product.name
				message = product.sale_line_warn_msg
				warning['title'] = title
				warning['message'] = message
				result = {'warning': warning}
				if product.sale_line_warn == 'block':
					order.product_id = False
					return result

			name = product.name_get()[0][1]
			if product.description_sale:
				name += '\n' + product.description_sale
			vals['name'] = name

			order._compute_tax_id()

			if order.order_id.pricelist_id and order.order_id.partner_id:
				vals['price_unit'] = self.env['account.tax']._fix_tax_included_price_company(order._get_display_price(product), product.taxes_id, order.tax_id, order.company_id)
			order.update(vals)

		return result
