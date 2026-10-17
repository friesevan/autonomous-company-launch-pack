# Setting Up Apple Developer Account

The Apple Developer membership belongs to one Investor, enrolled as an individual. That is fine for a small project with no LLC. The Mac mini uses that same Apple Account, in two places only, and the membership can become an organization membership later. Start these steps before anything else in the Setup Guide: identity verification is the one wait nobody controls.

## Whose account it is

With no LLC, there is no company that could own a developer account, so the membership is the enrolling Investor's own:

- **Their legal name.** The Apple Account's first and last name fields must hold it; a company name there delays approval. Apple may ask for a government ID that matches.
- **Their name as the seller.** It is shown on the App Store, and an individual can't use a trade name. The company's chosen name still appears inside the app and on its site.
- **Their contract, tax forms, and bank account.** Apple pays only the enrolling Investor, so agree in writing between you how costs and proceeds are split.
- **Effectively permanent.** Apple moves an individual membership to another person only rarely, with its own help, so choose the enrolling Investor once.

An individual membership is meant for exactly this: people and sole proprietors. It qualifies for the Small Business Program's 15% rate, and it can add up to 50 users in App Store Connect, which is how the other Investor gets access.

## Which Apple Account goes where

| Where | Which Apple Account | Why |
| --- | --- | --- |
| Developer Program enrollment and App Store Connect | The developer Apple Account: new, in the enrolling Investor's legal name, with the business email | The membership is that person's |
| Xcode on the Mac mini (**Settings > Accounts**) | The same developer Apple Account | With an individual membership, only the Account Holder can sign builds |
| The App Store app on the Mac mini, to install and update Xcode | The same account, signed in to the App Store only | Or download Xcode from developer.apple.com/download and skip the App Store |
| iCloud on the Mac mini (**System Settings**) | None: leave it signed out | Nothing the company does needs iCloud; staying out keeps Find My, Activation Lock, and iCloud sync out of the picture |
| Uploading builds and reading sales | No Apple Account: the App Store Connect API key | No two-factor prompts, and the key can be revoked |
| The other Investor in App Store Connect | Their own Apple Account, invited as a user | Access to App Store Connect, not to the developer team |
| TestFlight on your iPhones | Your own personal Apple Accounts | Testers accept an emailed invitation |

**One account, not two.** A separate "company" Apple Account wouldn't help: every Apple Account belongs to a person, and Xcode has to sign in as the Account Holder anyway. One dedicated account means one password and one stream of two-factor codes. Because it isn't signed in on any iPhone or iCloud, its codes arrive by text at the enrolling Investor's phone number.

## Steps

- [ ] **Decide which Investor enrolls** (above).
- [ ] **Create the developer Apple Account** at account.apple.com with the business email address (Setup Guide, section 4), the enrolling Investor's legal first and last name, and two-factor authentication with their phone number. Don't sign into it on your own iPhone or Mac.
- [ ] **Enroll in the Apple Developer Program ($99/year) as an individual** at developer.apple.com/programs/enroll, signed in with that account. Make sure the account's name, region, and phone number match the government ID you'll verify with. Expect anywhere from a day to several weeks.
- [ ] **App Store Connect agreements.** Once the membership is active, sign in to appstoreconnect.apple.com as the Account Holder, open **Business** (or **Agreements, Tax, and Banking**), accept the **Paid Apps Agreement**, and complete the tax forms and banking details. Nothing can be sold until these show as active.
- [ ] **EU trader status.** App Store Connect asks every developer to declare whether they are a "trader" under the EU Digital Services Act, and selling a paid app or in-app purchases points to yes. A trader's address (or a P.O. box), phone number, and email are shown on the app's EU product pages. Use the business email, a phone number you don't mind being public, and a P.O. box if you'd rather not show a home address (a P.O. box needs a receipt or bill as proof). Apple's page on this isn't legal advice, and neither is this.
- [ ] **Small Business Program.** Enroll at developer.apple.com/app-store/small-business-program/enroll as the Account Holder. New developers qualify. The 15% rate starts 15 days after the end of the Apple fiscal month in which you're approved, so month one will most likely be at 30%.
- [ ] **App Store Connect API key.** In App Store Connect, **Users and Access > Integrations > App Store Connect API**: generate a key with the **App Manager** role. Download the `.p8` file (it's offered once). On the Mac mini, place it at `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8` in the company's macOS account, and store the Key ID and Issuer ID in the Keychain or in `ops/secrets.local` (ignored by git). This lets the company upload builds and read sales without two-factor prompts.
- [ ] **On the Mac mini:** sign in to the App Store app only (not iCloud) with the developer Apple Account to install Xcode, or download Xcode from developer.apple.com/download. Then in Xcode, **Settings > Accounts**, add the same account so builds are signed automatically. Each sign-in asks for a two-factor code once.
- [ ] **The other Investor** as an App Store Connect user with the **App Manager** role (**Users and Access > Users**), so both of you can be internal TestFlight testers.
- [ ] **TestFlight** on both of your iPhones, signed in with your own Apple Accounts. Internal testers (App Store Connect users, up to 100) get builds within minutes of upload, with no Beta App Review. Builds expire after 90 days.

## Later, if it earns enough for an LLC

Nothing to do now; this is how the Apple side would move.

1. Form the LLC and get its free D-U-N-S Number.
2. Ask Apple to update the membership from individual to organization at developer.apple.com/contact/request/migrate-individual-account. The enrolling Investor must be a founder or cofounder of the LLC, and Apple may ask for business documents. Reported waits run from a day to months.
3. Apple's help page doesn't say what happens to existing apps, so confirm with Apple Developer Support before starting.

The fallback is to enroll the LLC separately and transfer the app to it. The app keeps its ratings, reviews, and bundle ID, and users keep getting updates; sales history from before the transfer stays with the old account. Either way, the seller name then becomes the LLC's.

None of this is legal or tax advice. A short consult with a tax professional on how the income is reported between the two of you is worth having.

## Sources

- [Become a member (enrollment requirements)](https://developer.apple.com/programs/enroll/)
- [Updating your account information (individual to organization)](https://developer.apple.com/help/account/membership/updating-your-account-information/)
- [Add and edit users (App Store Connect)](https://developer.apple.com/help/app-store-connect/manage-your-team/add-and-edit-users/)
- [EU Digital Services Act trader requirements](https://developer.apple.com/help/app-store-connect/manage-compliance-information/manage-european-union-digital-services-act-trader-requirements/)
- [Overview of app transfer](https://developer.apple.com/help/app-store-connect/transfer-an-app/overview-of-app-transfer/)
