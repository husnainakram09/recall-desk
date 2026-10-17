# Fixtures

## Notice: real, public MHRA text

`notice_el25a17.txt` and `notice_el25a17.pdf` are the MHRA Class 2 Medicines
Recall **EL(25)A/17**, Lercanidipine HCl 20mg Tablets, published 17 April 2025.

- Source: <https://www.gov.uk/drug-device-alerts/class-2-medicines-recall-lercanidipine-hcl-20mg-tablets-recordati-industria-el-25-a-slash-17>
- The PDF is the file published on GOV.UK, unmodified. Its SHA-256 is in
  `notice_el25a17.meta.json`.
- The `.txt` is the PDF's text layer as extracted by pypdf, with trailing
  whitespace removed per line. Nothing else is edited.

Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Source: MHRA, EL(25)A/17. This is a historical notice used for an educational
replay. Do not treat it as current guidance: check GOV.UK for the live status.

## Stock: synthetic

`stock_demo.csv` is **synthetic**. It is not real pharmacy stock and does not
describe any real pharmacy, patient or supply. Every site is labelled
`SYNTHETIC Demo Pharmacy`.

| Row | What it represents | Expected state |
| --- | --- | --- |
| A | Notice product, lot MD4L07 | exact_candidate |
| B | Notice product, other lot ZZ9TEST | not_matched_to_this_notice |
| C | Notice product, lot not recorded | needs_evidence |
| D | Mislabelled carton keyed as 10 mg, lot MD4L07, notice PL and GTIN | conflicting_identifiers |
| E | Different product sharing the lot string MD4L07 | not_matched_to_this_notice |
| F-L | Ordinary unrelated stock | not_matched_to_this_notice |

Rows A-D use the notice's real PL and GTIN. Product names are written the
way staff type them ("Lercanidipine 20mg tabs"), not the notice title.

Rows E-L use made-up identifiers: PL numbers under the placeholder company
code `99999`, and GTINs in the GS1 `02` prefix range, which is reserved for
restricted internal use and never assigned to trade items. Neither refers to
any real product.

`stock_edge_cases.csv` is also synthetic. It exercises PL label forms, a
miskeyed GTIN, a mislabelled carton, lot spacing, case and O/0 typos, a lot
range, missing evidence and four rows that must fail to parse (lines 14-17).

"Not matched to this notice" only means the row did not match this notice. It
does not establish that the stock is safe.
