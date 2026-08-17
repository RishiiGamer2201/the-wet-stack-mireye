# Sample data

The PDFs in this directory are **synthetic demonstration documents**. They are generated
deterministically by the seed command, so they are not committed to git:

```bash
cd apps/api && python -m app.seed --reset
```

| File | Kind | Contents |
| --- | --- | --- |
| `Aurora-DC1-Mechanical-Specification-SYNTHETIC.pdf` | specification | 3 pages of invented performance, physical, electrical and refrigerant requirements for CH-01, CH-02 and PDU-3 |
| `Northwind-NT-1100-Datasheet-SYNTHETIC.pdf` | manufacturer datasheet | The existing chiller's invented technical data |
| `Vertex-VX-1150-Submittal-SYNTHETIC.pdf` | submittal | The proposed substitution's invented technical data |

Every page carries a banner reading *"SYNTHETIC DEMONSTRATION DOCUMENT — values are invented for the
Wet Stack / Mireye prototype and are not real product or project data."* The manufacturers
(Northwind Thermal, Vertex Climate, Halden Cooling, Ferrous Power, Kestrel Energy) are fictional.

The source text lives in `apps/api/app/seed.py`, so the fixtures and the seeded equipment
configurations can never drift apart.

The ideation PDF at the repository root is the product brief. It is deliberately **not** ingested as
an engineering source document in the demo project.
