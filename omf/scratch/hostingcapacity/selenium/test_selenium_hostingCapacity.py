'''
Selenium Tests for the Hosting Capacity Model.

Browser: Chrome
Test Environment: Localhost
Tests:
- Presense of warnings when expected
	- reactive power warning
	- double warning for reactive power + buses not in circuit
- VoltVar Setting option works with different output from example files
'''
# Python Imports
from pathlib import Path

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import Select

# OMF Imports
from omf import _omfDir
# All these tests use Chrome, in the future I want to make firefox ones because I use firefox :D


def loginToOMF( driver, username, password ):
	username_field = driver.find_element(by=By.ID, value="username")
	password_field = driver.find_element(by=By.ID, value='password')
	username_field.send_keys(username)
	password_field.send_keys(password)
	password_field.send_keys(Keys.RETURN)


def deleteOldModel( driver, username, test_name ):
	href_model = "./model/" + username + "/" + test_name
	try:
		existing_model = driver.find_element(by=By.XPATH, value='//a[@href="' + href_model + '"]')
	except NoSuchElementException:
		return False
	if existing_model.is_displayed():
		existing_model.click()
		deleteButton = driver.find_element(by=By.ID, value="deleteButton")
		deleteButton.click()
		wait = WebDriverWait(driver, 1)
		alert = wait.until(expected_conditions.alert_is_present())
		alert.accept()
		return True
	return False


def findAndCreateHostingCapacityModel( test_name, driver, wait ):
	# Create hostingCapacity Model
	driver.find_element(by=By.ID, value="newModelButton").click()
	driver.find_element(by=By.XPATH, value="//a[contains(@href, 'hostingCapacity')]" ).click()
	# Not sure if waiting one second for the pop-up for the name is needed
	alert = wait.until(expected_conditions.alert_is_present())
	# Submit the test name
	alert.send_keys(test_name)
	alert.accept()
	# Wait until the page loads up
	wait.until(expected_conditions.staleness_of(driver.find_element(By.TAG_NAME, "html")))


def hostingCapacityReactivePowerWarning(url, username, password):
	'''
	Tests with a file containing kvar_reading with "None" as values
	Tests with a file with kvar_reading column not present

	- [X] Checks if both files lead to the error being present.
	- [X] AMI data table doesn't have the thermal column
	- TODO: [O] Ensures modelfree, modelbased, downline load coloring still there ( I check if the map is present ATM )
	'''
	# Create Model
	success = False
	test_name = "Selenium Test Hosting Capacity Reactive Power Warnings"
	driver = webdriver.Chrome()
	driver.get( url )
	wait = WebDriverWait(driver, 1)
	loginToOMF(driver, username=username, password=password)
	deleted = deleteOldModel(driver, username=username, test_name=test_name)
	if deleted:
		wait.until(expected_conditions.element_to_be_clickable((By.ID, "newModelButton")))
	findAndCreateHostingCapacityModel( test_name=test_name, driver=driver, wait=wait)
	# Setup Model
	# Upload NoneQ File
	testFile = "doc - input_mohcaData_NoneQ.csv"
	model_free_data_input = driver.find_element(by=By.ID, value="AmiDataFile")
	model_free_data_input.send_keys( str( Path("./", testFile).resolve() ) )
	# Run model
	driver.find_element(by=By.ID, value="runButton").click()
	# Wait 60 seconds for the model to run. I hate this timeout thing.
	WebDriverWait(driver, 60).until(expected_conditions.presence_of_element_located((By.ID, 'output')))

	### Test Results
	# Reactive Power warning
	reactive_power_warning = driver.find_element(by=By.ID, value="reactivePowerWarningInformation")
	try:
		assert( reactive_power_warning.is_displayed() == True )
	except AssertionError:
		print("FAILED: Warning Missing from Outputs :: Model Free Reactive Power :: html element: reactivePowerWarningInformation")
		success = False
	# Make sure map is still there
	map = driver.find_element(by=By.ID, value="hostingCapacityMap")
	try:
		assert ( map.is_displayed() == True )
	except AssertionError:
		print("FAILED: Map is missing from outputs")
		success = False

	headers = driver.find_element(By.ID, "AMIhostingCapacityTable").find_elements(By.CSS_SELECTOR, "tr:first-child th")
	expectedColumns = ["busname", "min_cap_allowed", "voltage_cap_kw"]
	try:
		assert ( len(headers) == len(expectedColumns) )
	except AssertionError:
		print(f"FAILED: Number of columns expected: 3, actual: {len(headers)} :: html element: AMIhostingCapacityTable")
		success = False

	# Checking Map for
	# 1. modelFree Coloring
	# 2. model-based and downline load coloring options
	# editMenu = driver.find_element(by=By.ID, value="editMenu") #Jenny
	# editButton = editMenu.find_element(by=By.TAG_NAME, value="button").click()

	# buttonsDict = {}
	# divOfEditMenuButtons = editButton.find_element(by=By.ID, value="contentdiv")
	# buttons = divOfEditMenuButtons.find_elements(By.TAG_NAME, value="button")
	# for button in buttons:
	# 	span_text = button.find_element(By.TAG_NAME, "span").text.strip()
	# 	buttonsDict[span_text] = button
	# WebDriverWait(driver, 60)
	# buttonsDict["Color circuit..."].click()
	driver.quit()
	success = True
	return success


def hostingCapacityDoubleWarnings(url, username, password):
	'''
	Hosting Capacity Selenium Test Double Warnings
	- File contains reactive power column with all None values
	- File also contains buses that are not in circuit

	Test ensures:
	- [X] Sandia's algorithm works with reactive power as none
	- [X] 2 warnings show up, not just 1
	- [X] Map is still there even though there's no colorby for model-based hosting capacity
	- TODO: [O] Both model-based and downline load coloring still there
	'''
	### Create Model
	success = False
	test_name = "Selenium Test Hosting Capacity Double Warnings"
	driver = webdriver.Chrome()
	driver.get( url )
	wait = WebDriverWait(driver, 1)
	loginToOMF(driver, username=username, password=password)
	deleted = deleteOldModel(driver, username=username, test_name=test_name)
	if deleted:
		wait.until(expected_conditions.element_to_be_clickable((By.ID, "newModelButton")))
	findAndCreateHostingCapacityModel( test_name=test_name, driver=driver, wait=wait)
	### Upload File(s) For Test
	# Upload File with Mis-Match Buses and None Values File (its the old 2024 file with None values)
	testFile = "doc - old_mohcaCustom_NoneQ.csv"
	model_free_data_input = driver.find_element(by=By.ID, value="AmiDataFile")
	model_free_data_input.send_keys( str( Path("./", testFile).resolve() ) )
	# Run model
	driver.find_element(by=By.ID, value="runButton").click()
	# Wait 60 seconds for the model to run. I hate this timeout thing.
	WebDriverWait(driver, 60).until(expected_conditions.presence_of_element_located((By.ID, 'output')))
	### Test Results
	# Check for both warnings
	# Reactive Power warning
	reactive_power_warning = driver.find_element(by=By.ID, value="reactivePowerWarningInformation")
	try:
		assert ( reactive_power_warning.is_displayed() == True )
	except AssertionError:
		print("FAILED: Warning Missing from Outputs :: Model Free Reactive Power :: htmlElement reactivePowerWarningInformation")
		success = False
	buses_mia_warning = driver.find_element(by=By.ID, value="mapWarningInformation")
	try:
		assert ( buses_mia_warning.is_displayed() == True )
	except AssertionError:
		print("FAILED: Warning Missing from Outputs :: Buses between files are different -> compromised map :: htmlElement mapWarningInformation")
		success = False
	# Make sure map is still there
	map = driver.find_element(by=By.ID, value="hostingCapacityMap")
	try:
		assert( map.is_displayed() == True )
	except AssertionError:
		print("FAILED: Map is missing from outputs")
		success = False
	driver.quit()
	success = True
	return success


def hostingCapacityVoltVar(url, username, password):
	''' Hosting Capacity Selenium Test VoltVar
	- Default File
	- Selects voltVAR
	- confirms that voltVAR choice has different outputs for thermal and voltage
	- Assumption - Tests MoHCA Stuff only
	'''
	# Create Model
	success = False
	test_name = "Selenium Test Hosting Capacity Volt Var Values"
	driver = webdriver.Chrome()
	driver.get( url )
	wait = WebDriverWait(driver, 1)
	loginToOMF(driver, username=username, password=password)
	deleted = deleteOldModel(driver, username=username, test_name=test_name)
	if deleted:
		wait.until(expected_conditions.element_to_be_clickable((By.ID, "newModelButton")))
	findAndCreateHostingCapacityModel( test_name=test_name, driver=driver, wait=wait )
	# Setup Model
	select = Select(driver.find_element(by=By.ID, value='dgInverterSetting'))
	select.select_by_visible_text('volt-VAR')
	select = Select(driver.find_element(by=By.ID, value='runModelBasedAlgorithm'))
	select.select_by_visible_text('Off')
	select = Select(driver.find_element(by=By.ID, value='runDownlineAlgorithm'))
	select.select_by_visible_text('Off')
	# Run Model
	driver.find_element(by=By.ID, value="runButton").click()
	# Wait 60 seconds for the model to run. I hate this timeout thing.
	WebDriverWait(driver, 60).until(expected_conditions.presence_of_element_located((By.ID, 'output')))
	# Everything above this will be the outline for other tests.
	thermalCapValue = driver.find_element(by=By.XPATH, value="/html/body/div[4]/div[5]/table/tbody/tr[2]/td[4]")
	thermalCapFloat = float(thermalCapValue.text)
	### Test Results
	try:
		assert ( 301.989591275621 == thermalCapFloat )
	except AssertionError:
		print(f"FAILED: Thermal VoltVar Value. Expected value: 301.989591275621 Actual Value: {thermalCapFloat} :: htmlElement AMIhostingCapacityTable")
		success = False
	voltageCapValue = driver.find_element(by=By.XPATH, value="/html/body/div[4]/div[5]/table/tbody/tr[2]/td[3]")
	voltageCapFloat = float(voltageCapValue.text)
	try:
		assert ( 11.78025085330058 == voltageCapFloat )
	except AssertionError:
		print(f"FAILED: Voltage VoltVar Value. Expected value: 11.78025085330058 Actual Value: {voltageCapValue} :: htmlElement AMIhostingCapacityTable")
		success = False
	driver.quit()
	success = True
	return success