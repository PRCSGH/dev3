# -*- coding: utf-8 -*-
#############################################################################
#
#    Bassam Infotech LLP
#
#    Copyright (C) 2020-2020 Bassam Infotech LLP (<https://www.bassaminfotech.com>).
#    Author: Mihran Thalhath (mihranthalhath@gmail.com) (mihranz7@gmail.com)
#
#############################################################################

{
    'name': "Multi Invoice Payment",
    'summary': """
        Register grouped or ungrouped partial payments against multiple invoices/bills.""",

    'description': """
        Register grouped or ungrouped partial payments against multiple invoices/bills. Odoo already have
        a register payment option for multiple invoices/bills. The issue with this is that it
        registers payment for the whole due amount. With the help of this module you can specify
        the exact amount to be paid against each selected invoice. Add an option to change partner
        which will automatically load all the open, unpaid invoices/bills to the lines. If invoices
        with different partners are selected, the payment cannot be grouped.

        DISCLAIMER: Currently, we do not support multi-currency payments.
    """,

    'author': "Bassam Infotech LLP",
    'website': "https://www.bassaminfotech.com",
    'license': 'OPL-1',
    'category': 'Accounting/Accounting',
    'version': '13.0.0.1',
    'support': "sales@bassaminfotech.com",
    'depends': ['account', 'account_batch_payment', 'sale'],
    'price': 30,
    'images': ['static/description/multi_invoice_payment_cover.png'],
    'currency': 'USD',
    'data': [
        'views/account_payment_register.xml',
        'views/payment_discount.xml',
        'views/account_batch_payment.xml',
        'views/menus.xml',
        'security/ir.model.access.csv'
    ],
    'installable': True,
    'auto_install': False,
}
