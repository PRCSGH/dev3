# -*- coding: utf-8 -*-
#################################################################################
# Author      : Acespritech Solutions Pvt. Ltd. (<www.acespritech.com>)
# Copyright(c): 2012-Present Acespritech Solutions Pvt. Ltd.
# All Rights Reserved.
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#################################################################################
import odoo
from odoo import http
from odoo.addons.web.controllers.main import Home, ensure_db
from odoo.addons.web.controllers import main
from odoo.http import request
import os
import sys
import jinja2
import werkzeug.utils
import werkzeug.wrappers
import json
from odoo.exceptions import AccessError, UserError, AccessDenied

if hasattr(sys, 'frozen'):
    # When running on compiled windows binary, we don't have access to package loader.
    path = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'views'))
    loader = jinja2.FileSystemLoader(path)
else:
    loader = jinja2.PackageLoader('odoo.addons.web', "views")

env = jinja2.Environment(loader=loader, autoescape=True)
env.filters["json"] = json.dumps
#----------------------------------------------------------
# OpenERP Web web Controllers
#----------------------------------------------------------
class Home(Home):

    @http.route('/web', type='http', auth="none")
    def web_client(self, s_action=None, **kw):
        ensure_db()
        if not request.session.uid:
            return werkzeug.utils.redirect('/web/login', 303)
        if kw.get('redirect'):
            return werkzeug.utils.redirect(kw.get('redirect'), 303)
        try :
            request.uid = request.session.uid
            context = request.env['ir.http'].webclient_rendering_context()
            request.env['ir.ui.menu'].clear_caches()
            menu_data = request.env['ir.ui.menu'].load_menus(request.session.debug)
            response = request.render('web.webclient_bootstrap',qcontext=context)
            response.headers['X-Frame-Options'] = 'DENY'
            return response
        except AccessError :
            return werkzeug.utils.redirect('/web/login?error=access')

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: