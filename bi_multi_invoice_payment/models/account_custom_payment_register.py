# -*- coding: utf-8 -*-
#############################################################################
#
#    Bassam Infotech LLP
#
#    Copyright (C) 2020-2020 Bassam Infotech LLP (<https://www.bassaminfotech.com>).
#    Author: Mihran Thalhath (mihranthalhath@gmail.com) (mihranz7@gmail.com)
#
#############################################################################

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from collections import defaultdict
from odoo.osv import expression

_logger = logging.getLogger(__name__)

# TODO: REMOVE THIS SHIT
MAP_INVOICE_TYPE_PARTNER_TYPE = {
    'out_invoice': 'customer',
    'out_refund': 'customer',
    'out_receipt': 'customer',
    'in_invoice': 'supplier',
    'Invoice': 'customer',
    'in_refund': 'supplier',
    'in_receipt': 'supplier',
}


# Let's make a copy of account.payment.register for our use case
class AccountCustomRegisterPayment(models.Model):
    _name = 'account.custom.payment.register'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Register Payment'
    _rec_name = 'journal_id'

    def get_payment_method(self):
        '''Select the Batch Deposit like default for the payment method.'''
        return self.env['account.payment.method'].search([
            ('code', '=', 'batch_payment')])

    partner_id = fields.Many2one('res.partner')
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one('account.journal', required=True,
                                 domain=[('type', 'in', ('bank', 'cash'))])
    payment_method_id = fields.Many2one(
        'account.payment.method', string='Payment Method Type',
        required=True, default=get_payment_method,
        help="Manual: Get paid by cash, check or any other method outside of Odoo.\n"
                                        "Electronic: Get paid automatically through a payment acquirer by requesting a transaction on a card saved by the customer when buying or subscribing online (payment token).\n"
                                        "Check: Pay bill by check and print it from Odoo.\n"
                                        "Batch Deposit: Encase several customer checks at once by generating a batch deposit to submit to your bank. When encoding the bank statement in Odoo, you are suggested to reconcile the transaction with the batch deposit.To enable batch deposit, module account_batch_payment must be installed.\n"
                                        "SEPA Credit Transfer: Pay bill from a SEPA Credit Transfer file you submit to your bank. To enable sepa credit transfer, module account_sepa must be installed ")
    invoice_ids = fields.Many2many(
        'account.move', 'account_invoice_custom_payment_rel_transient',
        'payment_id', 'invoice_id', string="Invoices", copy=False,
        readonly=True)
    group_payment = fields.Boolean(
        help="Only one payment will be created by partner (bank)/ currency.",
        default=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    company_currency_id = fields.Many2one(
        related='company_id.currency_id', string='Company Currency',
        readonly=True, store=True, help='Utility field to express amount currency')
    total_invoice_amount = fields.Monetary(
        currency_field="company_currency_id",
        compute='_compute_total_invoice_amount')
    invoice_type = fields.Selection([
        ('out_invoice', 'Customer Invoice'),
        ('in_invoice', 'Vendor Bill'),
    ], default='out_invoice')
    state = fields.Selection([('draft', 'Draft'),
                              ('posted', 'Posted')], default='draft'
    )
    register_line_ids = fields.One2many('account.payment.register.line',
                                        'account_payment_register_id', string='Lines')
    is_initial = fields.Boolean(string='Is Initial?', default=False)
    deposit_number = fields.Char(required=True)
    check_number = fields.Char(required=True)
    is_authorized_percent = fields.Boolean(
        compute='compute_authorized', store=True
    )
    total_balance = fields.Float(compute="compute_total_balance", store=True)

    @api.depends('total_balance', 'partner_id')
    def compute_authorized(self):
        '''Check if the logged user is authorized.
        TODO: Use a role for this validation

        '''
        for record in self:
            record.is_authorized_percent = True
            # update_lines(record)
            if False: # nuevo_grupo.id in self.env.user.groups_id
                record.is_authorized_percent = True
            else:
                max_disc = self.env['payment.discount'].search(
                    [], limit=1, order="id desc")
                any_discount_line = self.register_line_ids.filtered(
                    lambda x: x.discount)
                # * 100 because the widget percent in the view automatically
                # multiply by 100 then in the logic don't put this multiplication
                # and is necessary here for the comparison.
                if (max_disc.max_payment_discount < (record.total_balance * 100)
                    and any_discount_line):
                    # update_lines(record, False)
                    record.is_authorized_percent =  False

    @api.depends('register_line_ids.amount_payment')
    def compute_total_balance(self):
        '''Calculate the total balance percent.'''
        for rec in self:
            total_residual = sum(rec.register_line_ids.filtered(
                lambda l:l.discount).mapped('amount_residual'))
            total_discount = sum(rec.register_line_ids.filtered(
                lambda l:l.discount).mapped('amount_balance'))
            rec.total_balance = 0
            if total_residual > 0 and total_discount > 0:
                rec.total_balance = round(total_discount / total_residual, 6)

    def autofill_lines(self):
        '''Fill the pay amount with the current amount residual in the line.'''
        for line in self.register_line_ids:
            line.amount_payment = round(line.amount_residual, 2)
        return True
        # return {
        #     'name': _('Multi-Invoice Payment'),
        #     'res_model': 'account.custom.payment.register',
        #     'view_mode': 'form',
        #     'view_id': self.env.ref('bi_multi_invoice_payment.view_account_custom_payment_form_multi').id,
        #     'context': self.env.context,
        #     'target': 'current',
        #     'type': 'ir.actions.act_window',
        #     'res_id': self.id}

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """ Prepare the dict of values to balance the move.

            :param recordset move: the account.move to link the move line
            :param dict move: a dict of vals of a account.move which will be created later
            :param float amount: the amount of transaction that wasn't already reconciled
        TODO: Remove this method and implement a compute field who fill the lines
        field using the partner.

        """
        for record in self:
            # If the onchange is not getting triggered for the first time,
            # add the open invoices against the partner
            if not record.is_initial:
                if record.partner_id:
                    partner = record.partner_id.id
                    invoice_ids = self.env['account.move'].search([
                        ('partner_id', '=', record.partner_id.id),
                        ('move_type', '=', 'out_invoice'),
                        ('state', '=', 'posted'),
                        ('company_id', '=', self.env.company.id),
                        ('amount_residual', '>', 0)
                    ], order='invoice_date_due, date')
                    line_values = []
                    for each_move in invoice_ids:
                        values = (0, 0, {'move_id': each_move.id,
                                         'amount_payment': 0.0,
                                         'partner_id': each_move.partner_id.id})
                        line_values.append(values)
                    # Write the new values after unlinking existing lines
                    record.register_line_ids.unlink()
                    record.write({'register_line_ids': line_values,
                                  'invoice_ids': [(6, 0, invoice_ids.ids)],
                                  'partner_id': partner,
                                  'group_payment': True})
                else:
                    record.register_line_ids.unlink()
                    record.write({
                        # 'partner_id': False,
                        'is_initial': False,
                        'group_payment': False,
                    })
            # onchange is getting triggered for the first time, so add the invoices
            # in context to the lines
            else:
                record.is_initial = False
                active_ids = self._context.get('active_ids')
                if active_ids:
                    move_ids = self.env['account.move'].search([
                        ('id', 'in', active_ids)
                    ], order='invoice_date_due, date')
                    line_values = []
                    for each_move in move_ids:
                        values = (0, 0, {'move_id': each_move.id,
                                         'amount_payment': 0.0,
                                         'partner_id': each_move.partner_id.id})
                        line_values.append(values)
                    record.register_line_ids = line_values

    @api.depends('register_line_ids.amount_payment')
    def _compute_total_invoice_amount(self):
        for record in self:
            total_invoice_amount = 0
            for each_line in record.register_line_ids:
                total_invoice_amount += each_line.amount_payment
            record.total_invoice_amount = total_invoice_amount

    @api.model
    def default_get(self, fields):
        rec = super(AccountCustomRegisterPayment, self).default_get(fields)
        active_ids = self._context.get('active_ids')
        if not active_ids:
            return rec
        # Set is_initial as true to not trigger onchange changes for the first time.
        rec['is_initial'] = True
        invoices = self.env['account.move'].browse(active_ids)
        partner_ids = invoices.mapped('partner_id')
        # Set group payment as false if invoices with different partners are selected
        if len(partner_ids) > 1:
            rec['group_payment'] = False
            raise UserError(
                _("You can only register payments for the same client."))
        else:
            rec['partner_id'] = partner_ids.id
        # Check all invoices are open
        if any(invoice.state != 'posted' or
               invoice.payment_state  not in ('partial','not_paid') or not
               invoice.is_invoice() for invoice in invoices):
            msg_err = "You can only register payments for open & not-paid"+\
                      " invoices."
            raise UserError(_(msg_err))
        # Check all invoices are inbound or all invoices are outbound
        outbound_list = [invoice.is_outbound() for invoice in invoices]
        first_outbound = invoices[0].is_outbound()
        if any(x != first_outbound for x in outbound_list):
            raise UserError(_("You can only register at the same time for payment that are all inbound or all outbound"))
        if any(inv.company_id != invoices[0].company_id for inv in invoices):
            raise UserError(_("You can only register at the same time for payment that are all from the same company"))
        # Check the destination account is the same
        destination_account = invoices.line_ids.filtered(lambda line: line.account_internal_type in ('receivable', 'payable')).mapped('account_id')
        if len(destination_account) > 1:
            raise UserError(_('There is more than one receivable/payable account in the concerned invoices. You cannot group payments in that case.'))
        if 'invoice_ids' not in rec:
            rec['invoice_ids'] = [(6, 0, invoices.ids)]
        if 'journal_id' not in rec:
            rec['journal_id'] = self.env['account.journal'].search([
                ('company_id', '=', self.env.company.id),
                ('type', 'in', ('bank', 'cash'))], limit=1).id
        return rec

    @api.onchange('journal_id', 'invoice_ids')
    def _onchange_journal(self):
        active_ids = self._context.get('active_ids')
        invoices = self.env['account.move'].browse(active_ids)
        if self.journal_id and invoices:
            domain_journal = [('type', 'in', ('bank', 'cash')),
                              ('company_id', '=', invoices[0].company_id.id)]
            return {'domain': {'journal_id': domain_journal}}
        return {}

    def _prepare_payment_vals(self, invoices):
        '''Create the payment values.

        :param invoices: The invoices/bills to pay. In case of multiple
            documents, they need to be grouped by partner, bank, journal and
            currency.
        :return: The payment values as a dictionary.

        '''
        amount = self.total_invoice_amount
        # Filtered the invoices using the lines properties discount and
        # payment amount.
        filtered_inv = []
        for inv in invoices:
            line = self.register_line_ids.filtered(
                lambda l: l.move_id.id == inv.id)
            if line.discount or line.amount_payment > 0:
                filtered_inv.append(inv)
        communication = ", ".join(
            i.payment_reference or i.ref or i.name for i in filtered_inv)
        related_inv_char = str([i.id for i in filtered_inv])
        if self.group_payment:
            values = {
                'related_inv_char': related_inv_char,
                'use_bi_multi_inv_payment_module': True,
                'deposit_number': self.deposit_number,
                'check_number': self.check_number,
                'journal_id': self.journal_id.id,
                'payment_method_id': self.payment_method_id.id,
                'date': self.payment_date,
                'ref': communication,
                'payment_type': ('inbound' if amount > 0 else 'outbound'),
                'amount': self.total_invoice_amount,
                'currency_id': invoices[0].currency_id.id,
                'partner_id': invoices[0].commercial_partner_id.id,
                'partner_type': MAP_INVOICE_TYPE_PARTNER_TYPE[invoices[0].type_name],
                'partner_bank_id': invoices[0].partner_bank_id.id,
            }
        else:
            values = {
                'related_inv_char': related_inv_char,
                'use_bi_multi_inv_payment_module': True,
                'deposit_number': self.deposit_number,
                'check_number': self.check_number,
                'journal_id': self.journal_id.id,
                'payment_method_id': self.payment_method_id.id,
                'date': self.payment_date,
                'ref': communication,
                #'invoice_ids': [(6, 0, invoices.ids)],
                #'reconciled_invoice_ids': [(6, 0, invoice_ids)],
                'payment_type': ('inbound' if amount > 0 else 'outbound'),
                'amount': self.register_line_ids.filtered(
                    lambda x : x.move_id == invoices[0]).amount_payment,
                'currency_id': invoices[0].currency_id.id,
                'partner_id': invoices[0].commercial_partner_id.id,
                'partner_type': MAP_INVOICE_TYPE_PARTNER_TYPE[invoices[0].type_name],
                'partner_bank_id': invoices[0].partner_bank_id.id,
            }
        return values

    def _get_payment_group_key(self, invoice):
        """ Returns the grouping key to use for the given invoice when group_payment
        option has been ticked in the wizard.
        """
        return (invoice.commercial_partner_id, invoice.currency_id,
                invoice.partner_bank_id,
                MAP_INVOICE_TYPE_PARTNER_TYPE[invoice.type_name])

    def get_payments_vals(self):
        '''Compute the values for payments.

        :return: a list of payment values (dictionary).
        '''
        grouped = defaultdict(lambda: self.env["account.move"])
        invoices = self.invoice_ids
        if not invoices:
            invoices = self.register_line_ids.mapped('move_id')
        for inv in invoices:
            if self.group_payment:
                grouped[self._get_payment_group_key(inv)] += inv
            else:
                grouped[inv.id] += inv
        return [self._prepare_payment_vals(invoices) for invoices in grouped.values()]

    def validate_invoices(self):
        '''Validate if the selected invoices meet all the needed conditions.'''
        if not self.register_line_ids:
            raise UserError(_("No Invoices selected!"))
        if not self.is_authorized_percent:
            err_msg = "You have not authorization for create payments"+\
                      " with {p} % of Total Discount."
            raise UserError(_(err_msg.format(
                p=round(self.total_balance * 100, 2))))
        partner_ids = self.register_line_ids.mapped('move_id.partner_id.id')
        if len(partner_ids) > 1 and self.group_payment:
            raise UserError(_("You can't group payments when invoices with"+\
                              " different partners are selected!"))
        currency_ids = self.register_line_ids.mapped('move_id.currency_id.id')
        if len(currency_ids) > 1 or currency_ids[0] != self.env.company.currency_id.id:
            raise UserError(_("Sorry! We do not support multi currency as of now!"))
        move_ids = self.register_line_ids.mapped('move_id')
        if any(inv.company_id != move_ids[0].company_id for inv in move_ids):
            raise UserError(_("You can only register at the same time for payment"+\
                              " that are all from the same company"))
        move_types = set(self.register_line_ids.mapped('move_id.move_type'))
        if len(move_types) > 1:
            raise UserError(_("You can only register at the same time for payment"+\
                              " that are all inbound or all outbound"))

    def create_payments(self):
        '''Create payments according to the invoices.
        Having invoices with different commercial_partner_id or different type
        (Vendor bills with customer invoices) leads to multiple payments.
        In case of all the invoices are related to the same
        commercial_partner_id and have the same type, only one payment will be
        created.

        :return: The ir.actions.act_window to show created payments.
        '''
        # check some needed validations.
        self.validate_invoices()
        for line in self.register_line_ids:
            line.move_id.prepayment_amount = line.amount_payment
            if line.discount:
                line.credited_balance = line.amount_balance
                line.move_id.set_complete_paid = True

        payment_dict = self.get_payments_vals()
        payments = self.env['account.payment'].create(payment_dict)
        payments.use_bi_multi_inv_payment_module = True
        payment_amount_filter = lambda l: l.amount_payment > 0
        # Update the related_invoice_id field. This fields is an artificial
        # field for store the invoices related with the payment.
        for each_line in self.register_line_ids.filtered(payment_amount_filter):
            each_line.move_id.related_payment_id = payments.id
        # If grouped payment, use our methods, else use base ones
        note_credit = self.register_line_ids.filtered(lambda x: x.discount)
        for rec in note_credit:
            # rec.move_id.not_update_totals = True
            self.reverse_moves(rec.move_id.id, rec.amount_balance)
        action_vals = {
            'name': _('Payments'),
            'domain': [('id', 'in', payments.ids)],
            'res_model': 'account.payment',
            'view_id': False,
            'type': 'ir.actions.act_window',
        }
        self.write({'state': 'posted'})
        if len(payments) == 1:
            action_vals.update({'res_id': payments[0].id, 'view_mode': 'form'})
        else:
            action_vals['view_mode'] = 'tree,form'
        return action_vals

    def reverse_moves(self, move_id, amount_to_reverse):
        '''Create the reversal movement for the invoices sets like discount
        in the line.

        '''
        reversal_instance = self.env['account.move.reversal'].create(
            {'move_ids': [(6, 0,[move_id])],
             'refund_method': 'refund',
             'company_id': self.env.company.id});
        ret = reversal_instance.reverse_moves()
        self.update_credit_note(reversal_instance.new_move_ids,
                                amount_to_reverse)
        return True

    def update_credit_note(self, credit_note, amount_to_reverse):
        '''Update the credit note related to the invoice.
        In the odoo default process the credit note use all the product
        defined in the origin invoice but in this use case is only necessary
        have one product with the residual value, so update the needed lines
        and remove the unnecessaries.

        '''
        upd_line = '''
            Update account_move_line
            SET quantity=1,
                price_unit={price},
                price_subtotal={price_sbt},
                price_total={price_total},
                amount_residual={residual},
                amount_currency={amount_currency},
                debit={debit},
                credit={credit},
                balance={balance}
            WHERE id={id}
        '''
        if credit_note:
            # Find the tax move line, then after update with 0 remove it.
            tax_line = credit_note.line_ids.filtered(
                lambda x: x.tax_base_amount > 0)
            credit_line = credit_note.line_ids.filtered(
                lambda x: x.credit > 0)
            prod_line = credit_note.line_ids.filtered(
                lambda x: x.product_id.name != False)
            # Clean the quantity in all the lines 
            credit_note.line_ids.write({'quantity': 0,
                                        'price_unit': 0,
                                        'price_subtotal': 0,
                                        'price_total': 0,
                                        'amount_residual': 0,
                                        'debit': 0,
                                        'credit': 0,
                                        'balance': 0,
                                        'tax_base_amount': 0,
                                        'tax_ids': False})
            if any(tax_line):
                tax_line.unlink()
            # Update the credit line.
            self.env.cr.execute(upd_line.format(
                debit=0,
                amount_currency=(amount_to_reverse * -1),
                credit=amount_to_reverse,
                price=(amount_to_reverse * -1),
                price_sbt=(amount_to_reverse * -1),
                price_total=(amount_to_reverse * -1),
                residual=(amount_to_reverse * -1),
                balance=(amount_to_reverse * -1),
                id=credit_line.id))
            # Update the first product line
            self.env.cr.execute(upd_line.format(
                debit=amount_to_reverse,
                credit=0,
                amount_currency=amount_to_reverse,
                price=amount_to_reverse,
                price_sbt=amount_to_reverse,
                price_total=amount_to_reverse,
                residual=0,
                balance=amount_to_reverse,
                id=prod_line[0].id))
            prod_line[0].product_id = False
            prod_line[0].name = 'Discount by Client Payment'
            credit_note.write(
                {'line_ids': [(6, 0, [prod_line[0].id, credit_line[0].id])]})
            credit_note.write({
                'amount_untaxed': amount_to_reverse,
                'amount_total': amount_to_reverse,
                'amount_residual': amount_to_reverse,
                'amount_untaxed_signed': amount_to_reverse * -1,
                'amount_total_signed': amount_to_reverse * -1,
                'amount_residual_signed': amount_to_reverse * -1,
            })


class AccountPaymentRegisterLine(models.Model):
    _name = 'account.payment.register.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Account Payment Register Line'

    register_id = fields.Many2one('account.custom.payment.register')
                                  
    account_payment_register_id = fields.Many2one('account.custom.payment.register',
                                                  string='Register ID')
    move_id = fields.Many2one('account.move', string='Invoice/Bill',
                              required=True)
    company_currency_id = fields.Many2one(
        related='account_payment_register_id.company_currency_id',
        string='Company Currency',
        readonly=True, store=True,
        help='Utility field to express amount currency')
    amount_total = fields.Monetary(string='Amount Total',
                                   compute='_compute_amount_total_residual',
                                   currency_field='company_currency_id')
    amount_residual = fields.Monetary(string='Amount Due',
                                      compute='_compute_amount_total_residual',
                                      currency_field='company_currency_id')
    amount_payment = fields.Monetary(string='Payment Amount',
                                     currency_field='company_currency_id')
    amount_balance = fields.Monetary(string='Balance Amount',
                                     currency_field='company_currency_id')
    percent_balance = fields.Float(string='Balance Percent',
                                   compute="_compute_percent_balance",
                                   store=True)
    partner_id = fields.Many2one('res.partner', string='Partner',
                                 related='move_id.partner_id')
    discount = fields.Boolean(default=False, string="Discount")
    # is_authorized = fields.Boolean(default=False)
    
    credited_balance = fields.Float()

    @api.depends('move_id')
    def _compute_amount_total_residual(self):
        for record in self:
            if record.move_id:
                record.write({
                    'amount_total': record.move_id.amount_total,
                    'amount_residual': record.move_id.amount_residual
                })
            else:
                record.write({'amount_total': 0.0, 'amount_residual': 0.0})

    @api.depends('amount_balance', 'amount_total')
    def _compute_percent_balance(self):
        '''Field who calculate the percent balance.'''
        for rec in self:
            if rec.amount_total:
                rec.percent_balance = rec.amount_balance / rec.amount_total
            else:
                rec.percent_balance = 0

    @api.onchange('move_id')
    def _onchange_move_id(self):
        for record in self:
            if record.account_payment_register_id.partner_id and record.move_id:
                if record.partner_id != record.account_payment_register_id.partner_id:
                    raise UserError(_("You can't select invoices/bills with different partners!"))
            selected_move_ids = []
            for each_record in self.account_payment_register_id.register_line_ids:
                if each_record.move_id.id in selected_move_ids:
                    raise UserError(_("You can't select an invoice/bill multiple times!"))
                else:
                    selected_move_ids.append(each_record.move_id.id)

    @api.onchange('amount_residual', 'amount_payment')
    def onchange_amount_balance(self):
        self.amount_balance = self.amount_residual - self.amount_payment
