# Train_Val_Module_with_Seed
This is a  ten_fold_cross Train_Val_Test_Module with manually set seed.
In the first, it calculates the seed_avarage_val_acc and seed_avarage_test_acc over each folds for per seed,
where it takes the highest val acc over all epochs to be the seed_fold_val_acc 
and get the seed_fold_test_acc by evaluate the model using the parameters of the best seed_fold_val_acc model.
After, it calculates the average and std of test_acc and val_acc over seed_average_accs.
