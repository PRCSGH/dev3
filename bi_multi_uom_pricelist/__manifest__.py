# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

{
    "name" : "Product UOM based Pricelist",
    "version" : "14.0.0.2",
    "category" : "Sales",
    'summary': 'Apps for UOM based pricelist apply UOM on pricelist unit of measure based pricelist apply different uom on price-list multiple uom on price-list for multiple uom based pricelist on multi uom pricelist apply pricelist for product uom based pricelist',
    "description": """
    
   Multi UOM Pricelist in odoo apps,
   pricelist in odoo apps,
   uom pricelist in odoo apps,
   multi pricelist in odoo apps,
   sales pricelist in odoo apps,
   invoice pricelist in odoo apps,


    
    """,
    "author": "BrowseInfo",
    "website" : "https://www.browseinfo.in",
    "price": 29,
    "currency": 'EUR',
    "depends" : ['base','sale','stock','sale_management'],
    "data": [
        'views/product_template_inherited.xml',
        'views/product_pricelist.xml',
    ],
    'qweb': [
    ],
    "auto_install": False,
    "installable": True,
    "live_test_url":'https://youtu.be/NtcsJQQQ5m0',
    "images":["static/description/Banner.png"],
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
