import odoo.addons.decimal_precision as dp
from odoo import models, fields, api, _
from odoo.addons.sale_stock.models.sale_order import SaleOrderLine
from odoo.exceptions import Warning, ValidationError, UserError



class AccountMoveInherit(models.Model):
	_inherit = "account.move"

	pricelist_id = fields.Many2one('product.pricelist' ,string="Pricelist")

	def product_price_update(self):
		for lines in self.invoice_line_ids.filtered(lambda l: l.product_id and l.price_unit > 0.00):
			pricelist_item = self.pricelist_id.item_ids.filtered(
				lambda l: l.compute_price == 'fixed' and l.applied_on == '1_product' and l.uom_id.id == lines.uom_id.id)
			if pricelist_item:
				each_price = self.pricelist_id.item_ids.search([('product_tmpl_id', '=', lines.product_id.product_tmpl_id.id),
																('compute_price', '=', 'fixed'),
																('applied_on', '=', '1_product'),
																('pricelist_id', '=', self.pricelist_id.id),
																('uom_id','=',lines.uom_id.id)])
				if not each_price:
					self.pricelist_id.write({'item_ids': [(0, 0, {'applied_on': '1_product',
																  'product_id': lines.product_id.product_tmpl_id.id,
																  'uom_id' : lines.uom_id.id,
																  'fixed_price': lines.price_unit})]})
				else:
						each_price.fixed_price = lines.price_unit
						
			else:
				self.pricelist_id.write({'item_ids': [(0, 0, {'applied_on': '1_product',
															  'product_id': lines.product_id.product_tmpl_id.id,
															  'uom_id' : lines.uom_id.id,
															  'fixed_price': lines.price_unit
															  })]})



class AccountMoveLineInherit(models.Model):
	_inherit = 'account.move.line'


	@api.onchange('product_id')
	def _onchange_product_id(self):
		for line in self:
			if not line.product_id or line.display_type in ('line_section', 'line_note'):
				continue

			line.name = line._get_computed_name()
			line.account_id = line._get_computed_account()
			line.tax_ids = line._get_computed_taxes()
			line.product_uom_id = line._get_computed_uom()
			line.price_unit = line._get_computed_price_unit()
			price_unit = line._get_computed_price_unit()

            # Manage the fiscal position after that and adapt the price_unit.
            # E.g. mapping a price-included-tax to a price-excluded-tax must
            # remove the tax amount from the price_unit.
            # However, mapping a price-included tax to another price-included tax must preserve the balance but
            # adapt the price_unit to the new tax.
            # E.g. mapping a 10% price-included tax to a 20% price-included tax for a price_unit of 110 should preserve
            # 100 as balance but set 120 as price_unit.
			if line.tax_ids and line.move_id.fiscal_position_id:
				price_subtotal = line._get_price_total_and_subtotal()['price_subtotal']
				line.tax_ids = line.move_id.fiscal_position_id.map_tax(line.tax_ids._origin,partner=line.move_id.partner_id)
				accounting_vals = line._get_fields_onchange_subtotal(price_subtotal=price_subtotal,currency=line.move_id.company_currency_id)
				amount_currency = accounting_vals['amount_currency']
				business_vals = line._get_fields_onchange_balance(amount_currency=amount_currency)
				if 'price_unit' in business_vals:
					line.price_unit = business_vals['price_unit']
					price_unit = business_vals['price_unit']
					
					
			if self.product_uom_id and self.move_id.pricelist_id:
				price =dict((product_id, res_tuple[0]) for product_id, res_tuple in self.move_id.pricelist_id._compute_price_rule([(self.product_id, self.quantity, self.partner_id)], date=False, uom_id=self.product_uom_id.id).items())
				price_unit = price.get(self.product_id.id, 0.0)
            	        
			company = line.move_id.company_id
			line.price_unit = company.currency_id._convert(price_unit, line.move_id.currency_id, company, line.move_id.date)





	@api.onchange('product_uom_id')
	def _onchange_uom_id(self):
	    ''' Recompute the 'price_unit' depending of the unit of measure. '''
	    price_unit = self._get_computed_price_unit()
  	    
	    
	    # See '_onchange_product_id' for details.
	    taxes = self._get_computed_taxes()
	    if taxes and self.move_id.fiscal_position_id:
	        price_subtotal = self._get_price_total_and_subtotal(price_unit=price_unit, taxes=taxes)['price_subtotal']
	        accounting_vals = self._get_fields_onchange_subtotal(price_subtotal=price_subtotal, currency=self.move_id.company_currency_id)
	        balance = accounting_vals['debit'] - accounting_vals['credit']
	        price_unit = self._get_fields_onchange_balance(balance=balance).get('price_unit', price_unit)
  	
  	
	    if self.product_uom_id and self.move_id.pricelist_id:
	    	price =dict((product_id, res_tuple[0]) for product_id, res_tuple in self.move_id.pricelist_id._compute_price_rule([(self.product_id, self.quantity, self.partner_id)], date=False, uom_id=self.product_uom_id.id).items())
	    	price_unit = price.get(self.product_id.id, 0.0)
  	
	    # Convert the unit price to the invoice's currency.
	    company = self.move_id.company_id
	    self.price_unit = company.currency_id._convert(price_unit, self.move_id.currency_id, company, self.move_id.date)


