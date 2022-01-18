# © 2021 onDevelop.sa
# Autor: Idelis Gé Ramírez

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

    
class PaymentDiscount(models.Model):

    _name = 'payment.discount'
    _description = 'Used for define the max discount in payments.'

    max_payment_discount = fields.Integer()
    pretty_discount = fields.Integer(related='max_payment_discount')
