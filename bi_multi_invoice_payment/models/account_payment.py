# -*- coding: utf-8 -*-

import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from datetime import date

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    deposit_number = fields.Char()
    check_number = fields.Char()
    '''This is a great lack in the odoo core fields a data structure for
    store numbers. The way to join instances fail (6,0,0) so is necessary store
    the related id in this char format.'''
    related_inv_char = fields.Char()
    dime_q = fields.Char()
    use_bi_multi_inv_payment_module = fields.Boolean()
    related_invoice_ids = fields.One2many('account.move', 'related_payment_id')
    
    def _synchronize_from_moves(self, changed_fields):
        ''' Redefined for avoid a wrong validation of the move line count
        established to 1.
        
        Update the account.payment regarding its related account.move.
        Also, check both models are still consistent.
        :param changed_fields: A set containing all modified fields on account.move.
        '''
        if self._context.get('skip_account_move_synchronization'):
            return
        for pay in self.with_context(skip_account_move_synchronization=True):
            # After the migration to 14.0, the journal entry could be shared
            # between the account.payment and the
            # account.bank.statement.line. In that case, the synchronization
            #will only be made with the statement line.
            if pay.move_id.statement_line_id:
                continue
            move = pay.move_id
            move_vals_to_write = {}
            payment_vals_to_write = {}
            if 'journal_id' in changed_fields:
                if pay.journal_id.type not in ('bank', 'cash'):
                    raise UserError(
                        _("A payment must always belongs to a bank or cash journal."))
            if 'line_ids' in changed_fields:
                all_lines = move.line_ids
                liquidity_lines, counterpart_lines, writeoff_lines = pay._seek_for_lines()
                if len(liquidity_lines) != 1 or len(counterpart_lines) != 1:
                    if pay.related_inv_char:
                        pass
                    else:
                        raise UserError(_(
                            "The journal entry %s reached an invalid state relative to its payment.\n"
                            "To be consistent, the journal entry must always contains:\n"
                            "- one journal item involving the outstanding payment/receipts account.\n"
                            "- one journal item involving a receivable/payable account.\n"
                            "- optional journal items, all sharing the same account.\n\n"
                        ) % move.display_name)
                if writeoff_lines and len(writeoff_lines.account_id) != 1:
                    raise UserError(_(
                        "The journal entry %s reached an invalid state relative to its payment.\n"
                        "To be consistent, all the write-off journal items must share the same account."
                    ) % move.display_name)
                if any(line.currency_id != all_lines[0].currency_id for line in all_lines):
                    raise UserError(_(
                        "The journal entry %s reached an invalid state relative to its payment.\n"
                        "To be consistent, the journal items must share the same currency."
                    ) % move.display_name)

                if any(line.partner_id != all_lines[0].partner_id for line in all_lines):
                    raise UserError(_(
                        "The journal entry %s reached an invalid state relative to its payment.\n"
                        "To be consistent, the journal items must share the same partner."
                    ) % move.display_name)

                if counterpart_lines.account_id.user_type_id.type == 'receivable':
                    partner_type = 'customer'
                else:
                    partner_type = 'supplier'
                liquidity_amount = liquidity_lines.amount_currency
                move_vals_to_write.update({
                    'currency_id': liquidity_lines.currency_id.id,
                    'partner_id': liquidity_lines.partner_id.id,
                })
                payment_vals_to_write.update({
                    'amount': abs(liquidity_amount),
                    'payment_type': 'inbound' if liquidity_amount > 0.0 else 'outbound',
                    'partner_type': partner_type,
                    'currency_id': liquidity_lines.currency_id.id,
                    'destination_account_id': counterpart_lines.account_id.id,
                    'partner_id': liquidity_lines.partner_id.id,
                })

            move.write(move._cleanup_write_orm_values(move, move_vals_to_write))
            pay.write(move._cleanup_write_orm_values(pay, payment_vals_to_write))

    def _prepare_move_line_default_vals(self, write_off_line_vals=None):
        ''' Prepare the dictionary to create the default account.move.lines
        for the current payment.
        :param write_off_line_vals: Optional dictionary to create a write-off
        account.move.line easily containing:
            * amount:       The amount to be added to the counterpart amount.
            * name:         The label to set on the line.
            * account_id:   The account on which create the write-off.
        :return: A list of python dictionary to be passed to the
        account.move.line's 'create' method.

        '''
        if not self.use_bi_multi_inv_payment_module:
            return super(AccountPayment, self)._prepare_move_line_default_vals(
                write_off_line_vals=write_off_line_vals)
        self.ensure_one()
        write_off_line_vals = write_off_line_vals or {}
        if not self.journal_id.payment_debit_account_id or not self.journal_id.payment_credit_account_id:
            raise UserError(_(
                "You can't create a new payment without an outstanding payments/receipts account set on the %s journal.",
                self.journal_id.display_name))
        # Compute amounts.
        write_off_amount = write_off_line_vals.get('amount', 0.0)
        if self.payment_type == 'inbound':
            # Receive money.
            counterpart_amount = -self.amount
            write_off_amount *= -1
        elif self.payment_type == 'outbound':
            # Send money.
            counterpart_amount = self.amount
        else:
            counterpart_amount = 0.0
            write_off_amount = 0.0

        balance = self.currency_id._convert(counterpart_amount, self.company_id.currency_id, self.company_id, self.date)
        counterpart_amount_currency = counterpart_amount
        write_off_balance = self.currency_id._convert(write_off_amount, self.company_id.currency_id, self.company_id, self.date)
        write_off_amount_currency = write_off_amount
        currency_id = self.currency_id.id

        if self.is_internal_transfer:
            if self.payment_type == 'inbound':
                liquidity_line_name = _('Transfer to %s', self.journal_id.name)
            else: # payment.payment_type == 'outbound':
                liquidity_line_name = _('Transfer from %s', self.journal_id.name)
        else:
            liquidity_line_name = self.payment_reference

        # Compute a default label to set on the journal items.
        payment_display_name = {
            'outbound-customer': _("Customer Reimbursement"),
            'inbound-customer': _("Customer Payment"),
            'outbound-supplier': _("Vendor Payment"),
            'inbound-supplier': _("Vendor Reimbursement"),
        }
        default_line_name = self.env['account.move.line']._get_default_line_name(
            _("Internal Transfer") if self.is_internal_transfer else payment_display_name['%s-%s' % (self.payment_type, self.partner_type)],
            self.amount,
            self.currency_id,
            self.date,
            partner=self.partner_id)
        line_vals_list = [
            # Liquidity line.
            {
                'name': liquidity_line_name or default_line_name,
                'date_maturity': self.date,
                'amount_currency': -counterpart_amount_currency,
                'currency_id': currency_id,
                'debit': balance < 0.0 and -balance or 0.0,
                'credit': balance > 0.0 and balance or 0.0,
                'partner_id': self.partner_id.id,
                'account_id': self.journal_id.payment_debit_account_id.id if balance < 0.0 else self.journal_id.payment_credit_account_id.id
            }
        ]
        AccountMove = self.env['account.move']
        for invoice_id in eval(self.related_inv_char):
            invoice = AccountMove.search([('id', '=', invoice_id)])
            # Receivable / Payable.
            line_vals_list.append(
                {'name': self.payment_reference or default_line_name,
                 'invoice_origin_id': invoice_id,
                 'date_maturity': self.date,
                 'amount_currency': (invoice.prepayment_amount * -1),
                 'currency_id': currency_id,
                 'debit': 0,
                 'credit': invoice.prepayment_amount,
                 'partner_id': self.partner_id.id,
                 'account_id': self.destination_account_id.id
                }
            )
        if write_off_balance:
            # Write-off line.
            line_vals_list.append({
                'name': write_off_line_vals.get('name') or default_line_name,
                'amount_currency': -write_off_amount_currency,
                'currency_id': currency_id,
                'debit': write_off_balance < 0.0 and -write_off_balance or 0.0,
                'credit': write_off_balance > 0.0 and write_off_balance or 0.0,
                'partner_id': self.partner_id.id,
                'account_id': write_off_line_vals.get('account_id'),
            })
        return line_vals_list

    def action_post(self):
        '''Redefined for create a Batch Payment for the related payments.
        Using the field Deposit Number for group the payments and by each
        group create a batch payment.

        '''
        if not self.use_bi_multi_inv_payment_module:
            return super(AccountPayment, self).action_post()
        for payment in self:
            # TODO: Find why this fields have the related invoices and also
            # have the new credit notes and remove this unnecessary filter.
            only_related_invoices = payment.related_invoice_ids.filtered(
                lambda x:x.type_name == 'Invoice')
            payment.reconciled_invoice_ids = only_related_invoices
        default_meth = self.custom_post()
        self.create_batch_deposit()
        return default_meth

    def create_batch_deposit(self):
        '''Find if exist any other account.batch.payment with the given deposit
        number and in this case add this new payment. If don't exist create a
        new one.

        '''
        def find_old_batch_payment(deposit_number):
            '''Find/return if exist an account batch deposit with the given
            deposit number.

            '''
            return self.env['account.batch.payment'].search([
                ('name', '=', deposit_number),('state', '=', 'draft')], limit=1)

        old_batch = find_old_batch_payment(self.deposit_number)
        if old_batch:
            self.batch_payment_id = old_batch.id
        else:
            '''
            By some odoo core validation is not possible create a batch
            payment with this module bi_multi_invoice_payment. So is necessary
            insert directly in the database a new batch deposit and stablish
            a reationship with the payment if no exist a batch deposit with
            the reference like de payment. If already exist a batch deposit
            with the payment deposit number like reference, the current payment
            is add to this old batch deposit.
            TODO: REMOVE  THIS SQL

            '''
            insert_batch_payment_query = '''
                INSERT INTO account_batch_payment(
                    batch_type,
                    date,
                    state,
                    export_filename,
                    journal_id,
                    payment_method_id,
                    name)
                VALUES('inbound',
                       '{date}',
                       'draft',
                       '{export_filename}',
                       '{journal_id}',
                       '{payment_method_id}',
                       '{name}');'''
            self.env.cr.execute(insert_batch_payment_query.format(
                date=str(date.today()),
                export_filename=False,
                journal_id=self.journal_id.id,
                payment_method_id=self.payment_method_id.id,
                name=self.deposit_number))
            batch = self.env['account.batch.payment'].search([
                ('name', '=', self.deposit_number),
                ('state', '=', 'draft')], limit=1)
            self.batch_payment_id = batch.id
        return True

    def action_custom_register_payment(self):
        active_ids = self.env.context.get('active_ids')
        if not active_ids:
            return ''
        move_ids = self.env['account.move'].search([
            ('id', 'in', active_ids)
        ])
        type = move_ids.mapped('type')
        if not (all(x == type[0] for x in type)):
            raise UserError(_("You can only select customer invoice or vendor bill at a time!"))
        context = self.env.context
        if move_ids[0].type == 'out_invoice':
            context['default_invoice_type'] = 'out_invoice'
        elif move_ids[0].type == 'in_invoice':
            context['default_invoice_type'] = 'in_invoice'
        context['default_company_id'] = self.env.company.id
        context['default_company_currency_id'] = self.env.company.currency_id.id
        return {
            'name': _('Multi-Invoice Payment'),
            'res_model': 'account.custom.payment.register',
            'view_mode': 'form',
            'view_id': self.env.ref('bi_multi_invoice_payment.view_account_custom_payment_form_multi').id,
            'context': context,
            'target': 'new',
            'type': 'ir.actions.act_window',
        }

    def _prepare_payment_moves(self):
        ''' Prepare the creation of journal entries (account.move) by
        creating a list of python dictionary to be passed to the 'create'
        method.

        Example 1: outbound with write-off:

        Account             | Debit     | Credit
        ---------------------------------------------------------
        BANK                |   900.0   |
        RECEIVABLE          |           |   1000.0
        WRITE-OFF ACCOUNT   |   100.0   |

        Example 2: internal transfer from BANK to CASH:

        Account             | Debit     | Credit
        ---------------------------------------------------------
        BANK                |           |   1000.0
        TRANSFER            |   1000.0  |
        CASH                |   1000.0  |
        TRANSFER            |           |   1000.0

        :return: A list of Python dictionary to be passed
        to env['account.move'].create.

        '''
        # The below if sentence permit throw the odoo core default behavior
        # when the user create a payment in the any invoice without use the
        # bi_mult module or when is needee set the invoices as full paid.
        if (not self.use_bi_multi_inv_payment_module):
            #or self.payment_difference_handling == 'reconcile'):
            return super(AccountPayment, self)._prepare_payment_moves()
        all_move_vals = []
        for payment in self:
            company_currency = payment.company_id.currency_id
            # move_names = payment.move_name.split(payment._get_move_name_transfer_separator()) if payment.move_name else None
            move_names = False
            write_off_amount = 0
            if not payment.use_bi_multi_inv_payment_module:
                write_off_amount = payment.payment_difference_handling == 'reconcile' and -payment.payment_difference or 0.0
            if payment.payment_type in ('outbound', 'transfer'):
                counterpart_amount = payment.amount
                liquidity_line_account = payment.journal_id.default_account_id
            else:
                counterpart_amount = -payment.amount
                liquidity_line_account = payment.journal_id.default_account_id

            # Manage currency.
            if payment.currency_id == company_currency:
                # Single-currency.
                balance = counterpart_amount
                write_off_balance = write_off_amount
                counterpart_amount = write_off_amount = 0.0
                currency_id = False
            else:
                # Multi-currencies.
                balance = payment.currency_id._convert(counterpart_amount, company_currency, payment.company_id, payment.payment_date)
                write_off_balance = payment.currency_id._convert(write_off_amount, company_currency, payment.company_id, payment.payment_date)
                currency_id = payment.currency_id.id

            # Manage custom currency on journal for liquidity line.
            if payment.journal_id.currency_id and payment.currency_id != payment.journal_id.currency_id:
                # Custom currency on journal.
                if payment.journal_id.currency_id == company_currency:
                    # Single-currency
                    liquidity_line_currency_id = False
                else:
                    liquidity_line_currency_id = payment.journal_id.currency_id.id
                liquidity_amount = company_currency._convert(
                    balance, payment.journal_id.currency_id, payment.company_id, payment.payment_date)
            else:
                # Use the payment currency.
                liquidity_line_currency_id = currency_id
                liquidity_amount = counterpart_amount

            # Compute 'name' to be used in receivable/payable line.
            rec_pay_line_name = ''
            if payment.payment_type == 'transfer':
                rec_pay_line_name = payment.name
            else:
                if payment.partner_type == 'customer':
                    if payment.payment_type == 'inbound':
                        rec_pay_line_name += _("Customer Payment")
                    elif payment.payment_type == 'outbound':
                        rec_pay_line_name += _("Customer Credit Note")
                elif payment.partner_type == 'supplier':
                    if payment.payment_type == 'inbound':
                        rec_pay_line_name += _("Vendor Credit Note")
                    elif payment.payment_type == 'outbound':
                        rec_pay_line_name += _("Vendor Payment")
                if payment.reconciled_invoice_ids:
                    rec_pay_line_name += ': %s' % ', '.join(
                        payment.reconciled_invoice_ids.mapped('name'))

            # Compute 'name' to be used in liquidity line.
            if payment.payment_type == 'transfer':
                liquidity_line_name = _('Transfer to %s') % payment.destination_journal_id.name
            else:
                liquidity_line_name = payment.name
            # ==== 'inbound' / 'outbound' ====
            def get_account_move_line():
                '''Compute the needed values for create a line using each
                move .. called account.move in this version but in older 
                account.invoice.

                '''
                result = []
                # for invoice in self.invoice_ids:
                for invoice in self.reconciled_invoice_ids:
                    result.append(
                        (0, 0,
                         {'name': rec_pay_line_name,
                          'amount_currency': invoice.amount_residual + write_off_amount if currency_id else 0.0,
                          'currency_id': currency_id,
                           # in really this is other account move
                          'invoice_origin_id': invoice.id,
                          'debit': 0,
                          'credit': invoice.prepayment_amount,
                          'date_maturity': payment.date,
                          'partner_id': payment.partner_id.commercial_partner_id.id,
                          'account_id': payment.destination_account_id.id,
                          'payment_id': payment.id}))
                return result
            move_lines = get_account_move_line()
            move_lines.append(
                (0, 0, {
                    'name': liquidity_line_name,
                    'amount_currency': -liquidity_amount if liquidity_line_currency_id else 0.0,
                    'currency_id': liquidity_line_currency_id,
                    'debit': balance < 0.0 and -balance or 0.0,
                    'credit': balance > 0.0 and balance or 0.0,
                    'date_maturity': payment.date,
                    'partner_id': payment.partner_id.commercial_partner_id.id,
                    'account_id': liquidity_line_account.id,
                    'payment_id': payment.id}))
            move_vals = {
                'date': payment.date,
                'ref': payment.ref,
                'journal_id': payment.journal_id.id,
                'currency_id': payment.journal_id.currency_id.id or payment.company_id.currency_id.id,
                'partner_id': payment.partner_id.id,
                'line_ids': move_lines}
            if write_off_balance:
                # Write-off line.
                move_vals['line_ids'].append((0, 0, {
                    'name': payment.writeoff_label,
                    'amount_currency': -write_off_amount,
                    'currency_id': currency_id,
                    'debit': write_off_balance < 0.0 and -write_off_balance or 0.0,
                    'credit': write_off_balance > 0.0 and write_off_balance or 0.0,
                    'date_maturity': payment.date,
                    'partner_id': payment.partner_id.commercial_partner_id.id,
                    'account_id': payment.writeoff_account_id.id,
                    'payment_id': payment.id,
                }))
            if move_names:
                move_vals['name'] = move_names[0]
            all_move_vals.append(move_vals)
            # ==== 'transfer' ====
            if payment.payment_type == 'transfer':
                journal = payment.destination_journal_id

                # Manage custom currency on journal for liquidity line.
                if journal.currency_id and payment.currency_id != journal.currency_id:
                    # Custom currency on journal.
                    liquidity_line_currency_id = journal.currency_id.id
                    transfer_amount = company_currency._convert(balance, journal.currency_id, payment.company_id, payment.date)
                else:
                    # Use the payment currency.
                    liquidity_line_currency_id = currency_id
                    transfer_amount = counterpart_amount

                transfer_move_vals = {
                    'date': payment.date,
                    'ref': payment.ref,
                    'partner_id': payment.partner_id.id,
                    'journal_id': payment.destination_journal_id.id,
                    'line_ids': [
                        # Transfer debit line.
                        (0, 0, {
                            'name': payment.name,
                            'amount_currency': -counterpart_amount if currency_id else 0.0,
                            'currency_id': currency_id,
                            'debit': balance < 0.0 and -balance or 0.0,
                            'credit': balance > 0.0 and balance or 0.0,
                            'date_maturity': payment.date,
                            'partner_id': payment.partner_id.commercial_partner_id.id,
                            'account_id': payment.company_id.transfer_account_id.id,
                            'payment_id': payment.id,
                        }),
                        # Liquidity credit line.
                        (0, 0, {
                            'name': _('Transfer from %s') % payment.journal_id.name,
                            'amount_currency': transfer_amount if liquidity_line_currency_id else 0.0,
                            'currency_id': liquidity_line_currency_id,
                            'debit': balance > 0.0 and balance or 0.0,
                            'credit': balance < 0.0 and -balance or 0.0,
                            'date_maturity': payment.date,
                            'partner_id': payment.partner_id.commercial_partner_id.id,
                            'account_id': payment.destination_journal_id.default_credit_account_id.id,
                            'payment_id': payment.id})]}
                if move_names and len(move_names) == 2:
                    transfer_move_vals['name'] = move_names[1]
                all_move_vals.append(transfer_move_vals)
        return all_move_vals

    def custom_post(self):
        """ Create the journal items for the payment and update the payment's
        state to 'posted'.
        A journal entry is created containing an item in the source liquidity
        account (selected journal's default_debit or default_credit)
        and another in the destination reconcilable account
        (see _compute_destination_account_id).
        If invoice_ids is not empty, there will be one reconcilable move line
        per invoice to reconcile with.
        If the payment is a transfer, a second journal entry is created in the
        destination journal to receive money from the transfer account.

            Call custom_reconcile() method instead of reconcile()
        """
        # payment_amounts = {}
        # for move in self.invoice_ids:
        #     payment_amounts[move.id] = move.prepayment_amount
        if self.amount == 0:
            self.amount = self.total_invoice_amount
            # self.amount = self.env['account.payment']._compute_payment_amount(
            #     self.invoice_ids, self.currency_id, self.journal_id,
            #     self.payment_date)
        # If amount is positive it is customer related else vendor related
        if self.amount > 0:
            customer_payment = True
        elif self.amount < 0:
            customer_payment = False
        else:
            raise UserError(_("Nothing to invoice!"))
        # self.create_batch_deposit()
        AccountMove = self.env['account.move'].with_context(default_type='entry')
        for rec in self:        
            # if rec.state != 'draft':
            #     raise UserError(_("Only a draft payment can be posted."))
            if any(inv.state != 'posted' for inv in rec.reconciled_invoice_ids):
                raise ValidationError(_("The payment cannot be processed "+\
                                        "because the invoice is not open!"))
            # keep the name in case of a payment reset to draft
            if not rec.name:
                # Use the right sequence to set the name
                if rec.payment_type == 'transfer':
                    sequence_code = 'account.payment.transfer'
                else:
                    if rec.partner_type == 'customer':
                        if rec.payment_type == 'inbound':
                            sequence_code = 'account.payment.customer.invoice'
                        if rec.payment_type == 'outbound':
                            sequence_code = 'account.payment.customer.refund'
                    if rec.partner_type == 'supplier':
                        if rec.payment_type == 'inbound':
                            sequence_code = 'account.payment.supplier.refund'
                        if rec.payment_type == 'outbound':
                            sequence_code = 'account.payment.supplier.invoice'
                rec.name = self.env['ir.sequence'].next_by_code(
                    sequence_code, sequence_date=rec.payment_date)
                if not rec.name and rec.payment_type != 'transfer':
                    raise UserError(_("You have to define a sequence for %s in your company.") % (sequence_code,))
            rec.write({'state': 'posted'})
            AccountMove = self.env['account.move']
            for pay_move_line in rec.move_id.line_ids.filtered(
                    lambda l: l.invoice_origin_id):
                invoice = AccountMove.search([
                    ('id', '=', pay_move_line.invoice_origin_id)])
                line_funct = lambda x: (
                    x.debit > 0 and x.account_id.id == pay_move_line.account_id.id)
                line = invoice.line_ids.filtered(line_funct)
                AccountMoveLine = self.env['account.move.line']
                AccountMoveLine |= pay_move_line
                AccountMoveLine |= line
                AccountMoveLine.reconcile()
        return True
