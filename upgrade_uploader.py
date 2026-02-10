import pandas as pd

df = pd.read_csv("upgrades.tsv", sep="\t")

print(df)

# we need to turn the deliniated string "required types" into a second dataframe, of name, type for each element in each row

# create a new dataframe, without the "required types" column
df_without_required_types = df.drop(columns=["required types"])

# create a new dataframe, with the "required types" column
df_required_types = df["required types"].str.split(",", expand=True)



# readd the name column
df_required_types.insert(0, "name", df["name"])
df_required_types.columns = ["name", "type", "extra_type1", "extra_type2", "extra_type3"]
new_df = df_required_types.copy()
for index, row in df_required_types.iterrows():
    if row.values[2] is not None:
        new_row = pd.DataFrame({"name": [row.values[0]], "type": [row.values[2]], "extra_type1": [None], "extra_type2": [None], "extra_type3": [None]})
        new_df = pd.concat([new_df, new_row], ignore_index=True)
    if row.values[3] is not None:
        new_row = pd.DataFrame({"name": [row.values[0]], "type": [row.values[3]], "extra_type1": [None], "extra_type2": [None], "extra_type3": [None]})
        new_df = pd.concat([new_df, new_row], ignore_index=True)
    if row.values[4] is not None:
        new_row = pd.DataFrame({"name": [row.values[0]], "type": [row.values[4]], "extra_type1": [None], "extra_type2": [None], "extra_type3": [None]})
        new_df = pd.concat([new_df, new_row], ignore_index=True)


# now we remove the extra_type column
new_df = new_df.drop(columns=["extra_type1", "extra_type2", "extra_type3"])

df_required_types = new_df

del new_df

from models import ShopUpgrade, ShopUpgradeUnitTypes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

url = input("Enter the database URL: ")
engine = create_engine(url)
Session = sessionmaker(bind=engine)
session = Session()

# now we iterate over the df_without_required_types, and for each row, we query the name, if it exists, we update it, if it does't, we create it
for index, row in df_without_required_types.iterrows():
    print(row)
    # check if the name exists
    existing_upgrade = session.query(ShopUpgrade).filter(ShopUpgrade.name == row.values[0]).first()
    print(existing_upgrade)
    if existing_upgrade is None:
        new_upgrade = ShopUpgrade(**row)
        new_upgrade.required_upgrade = None if type(new_upgrade.required_upgrade) == float else new_upgrade.required_upgrade
        if new_upgrade.required_upgrade is not None:
            new_upgrade.required_upgrade_id = session.query(ShopUpgrade.id).filter(ShopUpgrade.name == new_upgrade.required_upgrade).first()
            new_upgrade.required_upgrade = None
        new_upgrade.refit_target = None if type(new_upgrade.refit_target) == float else new_upgrade.refit_target
        session.add(new_upgrade)
    else:
        for key, value in row.items():
            if key != "required_upgrade":
                setattr(existing_upgrade, key, value if type(value) != float and key != "cost" else None)
    session.commit()
for _, row in df_required_types.iterrows():
    # we need to create the shop_upgrade_unit_types, it should just be query the upgrade.id and write (id, [1]) to the database
    try:
        target_upgrade_id = session.query(ShopUpgrade.id).filter(ShopUpgrade.name == row.values[0]).first()

        # Ensure target_upgrade_id is not None before proceeding
        if target_upgrade_id is not None:
            Unittype = ShopUpgradeUnitTypes(shop_upgrade_id=target_upgrade_id[0], unit_type=row.values[1])
            session.add(Unittype)
            session.commit()  # Commit the transaction
        else:
            print(f"Warning: No ShopUpgrade found for name {row.values[0]}.")

    except Exception as e:
        print(f"Error occurred: {e}")
        session.rollback()  # Rollback the session on error
